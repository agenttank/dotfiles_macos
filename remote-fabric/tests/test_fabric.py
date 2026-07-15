from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fabric import inventory, reconcile, repositories, rollout, secrets, sessions, transport
from fabric.common import FabricError, atomic_json, audit, read_json


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {
            "HOME": str(self.root / "home"),
            "REMOTE_FABRIC_STATE": str(self.root / "state"),
            "REMOTE_FABRIC_CONFIG": str(self.root / "config"),
        }, clear=False)
        self.env.start()
        Path(os.environ["HOME"]).mkdir()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class InventoryTests(Isolated):
    def write_inventory(self, hosts):
        path = self.root / "hosts.json"
        path.write_text(json.dumps({"schema": 1, "hosts": hosts}))
        return path

    def test_rejects_duplicates_and_secret_keys(self):
        host = {"id": "x", "platform": "linux", "roles": ["compute"], "capabilities": ["pi"], "transport": "local"}
        with self.assertRaises(FabricError):
            inventory.load_inventory(self.write_inventory([host, host]))
        bad = {**host, "id": "y", "access_token": "seeded-secret"}
        with self.assertRaises(FabricError):
            inventory.load_inventory(self.write_inventory([bad]))

    def test_selection_is_deterministic_and_compatible(self):
        hosts = [
            {"id": "z", "platform": "wsl", "roles": ["compute"], "capabilities": ["pi"], "transport": "ssh", "ssh_alias": "z", "known_hosts_file": "~/known", "host_key_fingerprint": "SHA256:z", "priority": 1},
            {"id": "a", "platform": "wsl", "roles": ["compute"], "capabilities": ["pi"], "transport": "ssh", "ssh_alias": "a", "known_hosts_file": "~/known", "host_key_fingerprint": "SHA256:a", "priority": 1},
        ]
        data = inventory.load_inventory(self.write_inventory(hosts))
        self.assertEqual(inventory.select_host(data, "pi", remote=True)["id"], "a")
        data["hosts"][0]["runner_priorities"] = {"pi": 0}
        self.assertEqual(inventory.select_host(data, "pi", remote=True)["id"], "z")
        with self.assertRaises(FabricError):
            inventory.select_host(data, "orca", remote=True)


class TransportTests(Isolated):
    def test_wsl_command_is_encoded_and_argument_safe(self):
        host = {"id": "wsl", "transport": "ssh-wsl", "wsl_distro": "Ubuntu", "command_path": ["/usr/bin", "/bin"]}
        command = transport.remote_command(host, ["printf", "%s", "value with spaces; echo unsafe"])
        self.assertTrue(command.startswith("powershell.exe -NoProfile -NonInteractive -EncodedCommand "))
        import base64
        script = base64.b64decode(command.rsplit(" ", 1)[1]).decode("utf-16le")
        self.assertIn("'--distribution','Ubuntu','--exec'", script)
        self.assertIn("'value with spaces; echo unsafe'", script)


class AtomicConcurrencyTests(Isolated):
    def test_atomic_write_and_audit_contention(self):
        target = self.root / "state/value.json"
        errors = []
        def worker(index):
            try:
                atomic_json(target, {"index": index})
                audit("contention-test", index=index)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors, [])
        self.assertIn(read_json(target)["index"], range(100))
        events = list((self.root / "state/audit/events").glob("*.json"))
        self.assertEqual(len(events), 100)
        self.assertTrue(all(read_json(path)["event"] == "contention-test" for path in events))


class SessionTests(Isolated):
    def test_same_work_converges_to_one_receipt(self):
        data = {"schema": 1, "hosts": [{"id": "local", "platform": "macos", "transport": "local", "roles": ["compute"], "capabilities": ["pi"], "priority": 1}]}
        results, errors = [], []
        def worker():
            try: results.append(sessions.start(data, "pi", "repo", "abc123", "work-1", False, execute=True))
            except Exception as exc: errors.append(exc)
        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch("fabric.sessions.subprocess.run", return_value=completed):
            threads = [threading.Thread(target=worker) for _ in range(24)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len({item["uri"] for item in results}), 1)
        self.assertEqual(len(list((self.root / "state/receipts/sessions").glob("*.json"))), 1)

    def test_stale_receipt_recreates_missing_session(self):
        data = {"schema": 1, "hosts": [{"id": "local", "platform": "macos", "transport": "local", "roles": ["compute"], "capabilities": ["pi"], "priority": 1}]}
        success = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch("fabric.sessions.subprocess.run", return_value=success):
            sessions.start(data, "pi", "repo", "abc123", "restart", False, execute=True)
        missing = subprocess.CompletedProcess([], 1, "", "")
        with mock.patch("fabric.sessions.subprocess.run", side_effect=[missing, success]) as run:
            receipt = sessions.start(data, "pi", "repo", "abc123", "restart", False, execute=True)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(receipt["work_id"], "restart")
        events = [read_json(path)["event"] for path in (self.root / "state/audit/events").glob("*.json")]
        self.assertIn("session-restart", events)

    def test_dry_run_has_no_state_or_audit_side_effects(self):
        data = {"schema": 1, "hosts": [{"id": "local", "platform": "macos", "transport": "local", "roles": ["compute"], "capabilities": ["pi"], "priority": 1}]}
        preview = sessions.start(data, "pi", "repo", "abc123", "dry-run", False, execute=False)
        self.assertTrue(preview["dry_run"])
        self.assertFalse((self.root / "state/receipts").exists())
        self.assertFalse((self.root / "state/audit").exists())

    def test_remote_failure_never_falls_back(self):
        data = {"schema": 1, "hosts": [{"id": "local", "platform": "macos", "transport": "local", "roles": ["compute"], "capabilities": ["pi"]}]}
        with self.assertRaises(FabricError) as raised:
            sessions.start(data, "pi", "repo", "HEAD", "work", True, execute=False)
        self.assertEqual(raised.exception.code, 3)


class RolloutTests(Isolated):
    def test_acceptance_requires_every_gate_soak_and_identity(self):
        identity = "identity-a"
        now = 1_000_000.0
        records = {gate: [{"identity": identity, "passed": True, "observed_at": now}] for gate in rollout.GATES}
        records["soak_heartbeat"] = [{"identity": identity, "passed": True, "observed_at": now - rollout.SOAK_SECONDS + i * 900} for i in range(int(rollout.SOAK_SECONDS / 900) + 1)]
        with mock.patch("fabric.rollout._records", side_effect=lambda gate: records.get(gate, [])):
            result = rollout.evaluate(identity, now=now)
        self.assertTrue(result["accepted"])
        self.assertTrue(rollout.acceptance(identity))
        self.assertFalse(rollout.acceptance("identity-b"))
        with self.assertRaises(FabricError):
            rollout.set_remote_default(True, "identity-b")
        self.assertFalse(rollout.set_remote_default(False, "identity-b")["remote_default"])


class RepositoryTests(Isolated):
    def test_prepare_is_idempotent_and_refuses_mismatch(self):
        upstream = self.root / "upstream.git"
        subprocess = __import__("subprocess")
        subprocess.run(["git", "init", "--bare", str(upstream)], check=True, stdout=subprocess.DEVNULL)
        source = self.root / "source"
        subprocess.run(["git", "clone", str(upstream), str(source)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
        (source / "file").write_text("one")
        subprocess.run(["git", "-C", str(source), "add", "file"], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "one"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(source), "push", "origin", "HEAD:main"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        config_path = self.root / "repos.json"
        config_path.write_text(json.dumps({"schema": 1, "repositories": [{"id": "repo", "origin": str(upstream), "canonical_path": str(Path(os.environ["HOME"]) / "canonical/repo.git"), "worktree_root": str(Path(os.environ["HOME"]) / "worktrees")}]}))
        config = repositories.load_config(config_path)
        first = repositories.prepare(config, "repo", "main", "work-1")
        second = repositories.prepare(config, "repo", "main", "work-1")
        self.assertEqual(first["path"], second["path"])
        self.assertEqual(first["sha"], second["sha"])


class ReconcileTests(Isolated):
    def test_apply_is_idempotent_and_rollback_restores(self):
        source = self.root / "config/source.txt"
        source.parent.mkdir()
        source.write_text("new")
        destination = Path(os.environ["HOME"]) / ".config/app/value.txt"
        destination.parent.mkdir(parents=True)
        destination.write_text("old")
        created = Path(os.environ["HOME"]) / ".config/app/created.txt"
        manifest_path = self.root / "config/manifest.json"
        manifest_path.write_text(json.dumps({"schema": 1, "files": [
            {"source": "source.txt", "destination": str(destination)},
            {"source": "source.txt", "destination": str(created)}
        ]}))
        manifest = reconcile.load_manifest(manifest_path)
        first = reconcile.apply(manifest)
        self.assertEqual(destination.read_text(), "new")
        self.assertTrue(created.exists())
        self.assertFalse(reconcile.apply(manifest)["changed"])
        reconcile.rollback(first["generation"])
        self.assertEqual(destination.read_text(), "old")
        self.assertFalse(created.exists())


class SecretTests(Isolated):
    def test_provision_does_not_persist_value_in_state_or_audit(self):
        seeded = "SEED-SECRET-DO-NOT-LEAK"
        broker = self.root / "broker"
        broker.write_text(f"#!/bin/sh\n[ \"$1\" = status ] && {{ echo ready; exit 0; }}\nprintf '%s' '{seeded}'\n")
        broker.chmod(broker.stat().st_mode | stat.S_IXUSR)
        destination = Path(os.environ["HOME"]) / ".config/provider/auth"
        path = self.root / "manifest.json"
        path.write_text(json.dumps({"schema": 1, "entries": [{"id": "provider", "broker_argv": [str(broker)], "destination": str(destination)}]}))
        result = secrets.provision_local(secrets.load_manifest(path))
        self.assertEqual(result["provisioned"], ["provider"])
        self.assertEqual(destination.read_text(), seeded)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        for file in (self.root / "state").rglob("*"):
            if file.is_file():
                self.assertNotIn(seeded, file.read_text(errors="ignore"))


if __name__ == "__main__":
    unittest.main()

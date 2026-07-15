from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .common import FabricError, audit, canonical, config_root, digest, read_json, state_root
from .inventory import default_inventory, inventory_identity, load_inventory, local_capabilities, select_host
from . import reconcile, repositories, rollout, secrets, sessions
from .transport import remote_command, ssh_base


def emit(value: Any, json_mode: bool = False) -> None:
    if json_mode:
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(value, indent=2, sort_keys=True))


def fabric_identity(inventory: dict[str, Any]) -> str:
    root = Path(__file__).resolve().parents[3]
    try:
        release = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False).stdout.strip()
    except OSError:
        release = "unversioned"
    source_root = Path(__file__).resolve().parents[2]
    source_hashes = {}
    for path in sorted(source_root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            source_hashes[str(path.relative_to(source_root))] = digest(path.read_bytes().hex())
    config = {"inventory": inventory_identity(inventory), "release": release or "unversioned", "source": digest(source_hashes)}
    return digest(config)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fabric")
    p.add_argument("--json", action="store_true")
    p.add_argument("--inventory", type=Path)
    sub = p.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("inventory")
    inv.add_argument("action", choices=("validate", "list"))

    probe = sub.add_parser("probe")
    probe.add_argument("--host")
    probe.add_argument("--remote", action="store_true")

    select = sub.add_parser("select")
    select.add_argument("--runner", required=True, choices=("orca", "pi", "build"))
    select.add_argument("--requires", default="")
    select.add_argument("--host")
    select.add_argument("--remote", action="store_true")

    rec = sub.add_parser("reconcile")
    rec.add_argument("action", choices=("plan", "apply", "rollback"))
    rec.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[2] / "config/deployments.json")
    rec.add_argument("--generation")

    sec = sub.add_parser("secrets")
    sec.add_argument("action", choices=("check", "provision"))
    sec.add_argument("--manifest", type=Path, default=config_root() / "secret-manifest.json")

    repo = sub.add_parser("repo")
    repo.add_argument("action", choices=("prepare",))
    repo.add_argument("--config", type=Path, default=config_root() / "repositories.json")
    repo.add_argument("--repo", required=True)
    repo.add_argument("--ref", required=True)
    repo.add_argument("--work-id", required=True)

    hand = sub.add_parser("handoff")
    hand.add_argument("action", choices=("check",))
    hand.add_argument("--path", type=Path, default=Path.cwd())
    hand.add_argument("--target", required=True)

    ses = sub.add_parser("session")
    ses.add_argument("action", choices=("start", "locate", "attach"))
    ses.add_argument("--runner", choices=("orca", "pi", "build"))
    ses.add_argument("--repo")
    ses.add_argument("--ref", default="HEAD")
    ses.add_argument("--work-id", required=True)
    ses.add_argument("--host")
    mode = ses.add_mutually_exclusive_group()
    mode.add_argument("--remote", action="store_true")
    mode.add_argument("--local", action="store_true")
    ses.add_argument("--worktree")
    ses.add_argument("--dry-run", action="store_true")

    route = sub.add_parser("routing")
    route.add_argument("action", choices=("status", "enable-remote-default", "disable-remote-default"))

    roll = sub.add_parser("rollout")
    roll.add_argument("action", choices=("status", "evaluate", "record"))
    roll.add_argument("--gate", choices=(*rollout.GATES, "soak_heartbeat"))
    roll.add_argument("--passed", action="store_true")
    roll.add_argument("--observed-at", type=float)

    health = sub.add_parser("health")
    health.add_argument("--all", action="store_true")

    canary = sub.add_parser("canary")
    canary.add_argument("kind", choices=("transport", "repository", "provider"))
    canary.add_argument("--host", required=True)
    canary.add_argument("--remote", action="store_true", required=True)
    canary.add_argument("--provider")
    canary.add_argument("--max-cost", type=float)

    au = sub.add_parser("audit")
    au.add_argument("action", choices=("show",))
    au.add_argument("--jsonl", action="store_true")
    return p


def _probe(host: dict[str, Any]) -> dict[str, Any]:
    if not host.get("enabled", True):
        return {"host": host["id"], "healthy": True, "enabled": False, "skipped": "disabled"}
    if host.get("transport", "local") == "local":
        actual = local_capabilities()
        return {"host": host["id"], "healthy": True, "capabilities": sorted(actual), "platform": platform.system().lower()}
    probe_script = "uname -s; for c in git python3 tmux pi orca codex claude; do command -v \"$c\" 2>/dev/null || true; done"
    command = [*ssh_base(host), "--", remote_command(host, ["sh", "-c", probe_script])]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False)
    return {"host": host["id"], "healthy": completed.returncode == 0, "output": completed.stdout.splitlines()[:12]}


def main(argv: Optional[list[str]] = None) -> int:
    args = parser().parse_args(argv)
    json_mode = args.json
    try:
        inventory = load_inventory(args.inventory)
        identity = fabric_identity(inventory)
        result: Any
        if args.command == "inventory":
            result = {"schema": 1, "valid": True, "identity": inventory_identity(inventory), "hosts": inventory["hosts"] if args.action == "list" else len(inventory["hosts"])}
        elif args.command == "probe":
            if args.remote:
                host = next((h for h in inventory["hosts"] if h["id"] == args.host), None)
                if not host or host.get("transport") not in {"ssh", "ssh-wsl"}:
                    raise FabricError("remote probe requires a configured SSH host", 3)
            else:
                host = next((h for h in inventory["hosts"] if h.get("transport", "local") == "local"), {"id": "local"})
            result = _probe(host)
        elif args.command == "select":
            result = select_host(inventory, args.runner, {x for x in args.requires.split(",") if x}, args.remote, args.host)
        elif args.command == "reconcile":
            if args.action == "rollback":
                if not args.generation:
                    raise FabricError("--generation is required")
                result = reconcile.rollback(args.generation)
            else:
                manifest = reconcile.load_manifest(args.manifest)
                result = reconcile.plan(manifest) if args.action == "plan" else reconcile.apply(manifest)
        elif args.command == "secrets":
            manifest = secrets.load_manifest(args.manifest)
            result = secrets.check(manifest) if args.action == "check" else secrets.provision_local(manifest)
        elif args.command == "repo":
            result = repositories.prepare(repositories.load_config(args.config), args.repo, args.ref, args.work_id)
        elif args.command == "handoff":
            result = repositories.handoff_check(args.path, args.target)
        elif args.command == "session":
            if args.action == "locate":
                result = sessions.locate(args.work_id)
            elif args.action == "attach":
                result = sessions.attach(args.work_id, execute=not args.dry_run)
            else:
                if not args.runner or not args.repo:
                    raise FabricError("session start requires --runner and --repo")
                route = rollout.routing()
                remote = args.remote or (route.get("remote_default") is True and not args.local)
                if remote and not args.remote and not rollout.acceptance(identity):
                    raise FabricError("remote default is stale or unaccepted", 10, "rollout-blocked")
                result = sessions.start(inventory, args.runner, args.repo, args.ref, args.work_id, remote, args.host, args.worktree, execute=not args.dry_run)
        elif args.command == "routing":
            if args.action == "status":
                result = {**rollout.routing(), "acceptance_current": rollout.acceptance(identity)}
            else:
                result = rollout.set_remote_default(args.action == "enable-remote-default", identity)
        elif args.command == "rollout":
            if args.action == "evaluate":
                result = rollout.evaluate(identity)
            elif args.action == "record":
                if not args.gate:
                    raise FabricError("--gate is required")
                path = rollout.record_evidence(args.gate, args.passed, identity, args.observed_at)
                result = {"schema": 1, "recorded": str(path), "gate": args.gate, "passed": args.passed}
            else:
                path = state_root() / "rollout/acceptance-v1.json"
                result = read_json(path, {"schema": 1, "accepted": False, "identity": identity})
        elif args.command == "health":
            result = {"schema": 1, "hosts": [_probe(host) for host in inventory["hosts"]]}
            result["healthy"] = all(host["healthy"] for host in result["hosts"])
        elif args.command == "canary":
            if not args.remote:
                raise FabricError("canaries require explicit --remote", 10)
            host = next((h for h in inventory["hosts"] if h["id"] == args.host), None)
            if not host:
                raise FabricError("unknown host", 3)
            if args.kind == "provider" and (not args.provider or args.max_cost is None or args.max_cost <= 0):
                raise FabricError("provider canary requires --provider and positive --max-cost")
            probe = _probe(host)
            passed = probe["healthy"]
            if args.kind == "provider" and passed:
                spec = host.get("provider_canaries", {}).get(args.provider)
                if not isinstance(spec, dict) or not isinstance(spec.get("argv"), list):
                    raise FabricError("provider canary is not declared for host", 2, "invalid")
                ceiling = float(spec.get("max_cost", 0))
                if ceiling <= 0 or args.max_cost > ceiling:
                    raise FabricError("requested provider cost exceeds inventory ceiling", 5, "safety")
                argv = spec["argv"]
                if not argv or not all(isinstance(item, str) for item in argv):
                    raise FabricError("provider canary argv is invalid")
                command = [*ssh_base(host), "--", remote_command(host, argv)] if host.get("transport") in {"ssh", "ssh-wsl"} else argv
                completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False)
                passed = completed.returncode == 0
                if passed:
                    rollout.record_evidence("real_provider_calls", True, identity, details={"host": args.host, "provider": args.provider})
            result = {"schema": 1, "kind": args.kind, "host": args.host, "passed": passed, "provider": args.provider, "max_cost": args.max_cost}
            audit("canary", kind=args.kind, host=args.host, passed=result["passed"], provider=args.provider)
        elif args.command == "audit":
            records = [read_json(path) for path in sorted((state_root() / "audit/events").glob("*.json"))] if (state_root() / "audit/events").exists() else []
            if args.jsonl:
                for record in records:
                    print(canonical(record).decode())
                return 0
            result = {"schema": 1, "events": records}
        else:
            raise FabricError("unsupported command")
        emit(result, json_mode)
        return 0
    except FabricError as exc:
        payload = {"schema": 1, "ok": False, "error": {"category": exc.category, "message": str(exc), "code": exc.code}}
        if json_mode:
            print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        else:
            print(f"fabric: {exc}", file=sys.stderr)
        return exc.code
    except subprocess.TimeoutExpired:
        print(json.dumps({"schema": 1, "ok": False, "error": {"category": "timeout", "code": 4}}) if json_mode else "fabric: operation timed out", file=sys.stdout if json_mode else sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())

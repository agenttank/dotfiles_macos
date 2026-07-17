from __future__ import annotations

import hashlib
import shlex
import subprocess
from pathlib import Path
from typing import Any, Optional

from .common import FabricError, atomic_json, audit, canonical, lock, read_json, require_id, state_root
from .inventory import select_host
from .transport import remote_command, ssh_base


def session_metadata(host: dict[str, Any], runner: str, repo: str, ref: str, work_id: str) -> dict[str, Any]:
    require_id(repo, "repo id")
    require_id(work_id, "work id")
    if not ref or len(ref) > 200 or any(ch in ref for ch in "\r\n\0"):
        raise FabricError("invalid ref")
    base = {"host": host["id"], "runner": runner, "repo": repo, "ref": ref, "work_id": work_id}
    suffix = hashlib.sha256(canonical(base)).hexdigest()[:12]
    session_id = f"rf-{repo[:18]}-{work_id[:18]}-{suffix}"
    return {"schema": 1, **base, "session_id": session_id, "uri": f"fabric://session/{session_id}"}


def receipt_path(session_id: str) -> Path:
    return state_root() / "receipts/sessions" / f"{require_id(session_id, 'session id')}.json"


def _runner_command(meta: dict[str, Any], worktree: Optional[str] = None) -> list[str]:
    runner = meta["runner"]
    if runner == "orca":
        command = ["sh", "-lc", 'orca open && exec "${SHELL:-/bin/sh}"']
    elif runner == "pi":
        command = ["pi"]
    elif runner == "build":
        command = ["sh", "-lc", "exec ${SHELL:-/bin/sh}"]
    else:
        raise FabricError(f"unsupported runner: {runner}")
    if worktree:
        return ["sh", "-lc", f"cd -- {shlex.quote(worktree)} && exec {shlex.join(command)}"]
    return command


def start(inventory: dict[str, Any], runner: str, repo: str, ref: str, work_id: str, remote: bool, host_id: Optional[str] = None, worktree: Optional[str] = None, execute: bool = True) -> dict[str, Any]:
    host = select_host(inventory, runner, remote=remote, host_id=host_id)
    meta = session_metadata(host, runner, repo, ref, work_id)
    path = receipt_path(meta["session_id"])
    tmux = ["tmux", "new-session", "-d", "-s", meta["session_id"], *(_runner_command(meta, worktree))]
    if remote:
        remote_shell = remote_command(host, tmux)
        base = ssh_base(host)
        command = [*base, "--", remote_shell]
        check = [*base, "--", remote_command(host, ["tmux", "has-session", "-t", meta["session_id"]])]
        attach = [*base[:-1], "-t", base[-1], "--", remote_command(host, ["tmux", "attach", "-t", meta["session_id"]])]
    else:
        command = tmux
        check = ["tmux", "has-session", "-t", meta["session_id"]]
        attach = ["tmux", "attach", "-t", meta["session_id"]]
    if not execute:
        return {**meta, "remote": remote, "dry_run": True, "attach_argv": attach, "launch_argv": command}
    with lock(f"session/{meta['session_id']}", "session-start", timeout=30):
        restarted = False
        if path.exists():
            existing = read_json(path)
            if {k: existing.get(k) for k in meta} != meta:
                raise FabricError("session receipt collision", 5, "collision")
            alive = subprocess.run(check, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)
            if alive.returncode == 0:
                return existing
            restarted = True
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
        if completed.returncode != 0:
            raise FabricError(f"session launch failed ({completed.returncode})", 8, "runner")
        receipt = {**meta, "remote": remote, "attach_argv": attach, "launch_argv": None}
        atomic_json(path, receipt)
        audit("session-restart" if restarted else "session-start", session_id=meta["session_id"], host=host["id"], runner=runner, remote=remote)
        return receipt


def locate(work_id: str) -> dict[str, Any]:
    require_id(work_id, "work id")
    folder = state_root() / "receipts/sessions"
    matches = [read_json(path) for path in folder.glob("*.json")] if folder.exists() else []
    matches = [item for item in matches if item.get("work_id") == work_id]
    if len(matches) != 1:
        raise FabricError(f"expected one session for work id, found {len(matches)}", 5, "ambiguous")
    return matches[0]


def attach(work_id: str, execute: bool = True) -> dict[str, Any]:
    receipt = locate(work_id)
    argv = receipt["attach_argv"]
    if execute:
        raise SystemExit(subprocess.call(argv))
    return {"schema": 1, "uri": receipt["uri"], "host": receipt["host"], "attach_argv": argv}

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Optional

from .common import FabricError, config_root, digest, read_json, require_id

FORBIDDEN_KEYS = {"secret", "token", "password", "private_key", "auth", "credential"}
RUNNER_ROLES = {"orca": "orca", "pi": "compute", "build": "compute"}


def default_inventory() -> Path:
    override = os.environ.get("REMOTE_FABRIC_INVENTORY")
    if override:
        return Path(override)
    configured = config_root() / "hosts.json"
    if configured.exists():
        return configured
    return Path(__file__).resolve().parents[2] / "inventory/hosts.json"


def _reject_sensitive(value: Any, trail: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            if lowered in FORBIDDEN_KEYS or any(word in lowered for word in ("password", "privatekey", "access_token")):
                raise FabricError(f"secret-like inventory key forbidden at {trail}.{key}", 5, "safety")
            _reject_sensitive(item, f"{trail}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive(item, f"{trail}[{index}]")


def load_inventory(path: Optional[Path] = None) -> dict[str, Any]:
    path = path or default_inventory()
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("hosts"), list):
        raise FabricError("inventory must be {schema: 1, hosts: [...]}")
    _reject_sensitive(data)
    seen: set[str] = set()
    for host in data["hosts"]:
        if not isinstance(host, dict):
            raise FabricError("each host must be an object")
        host_id = require_id(str(host.get("id", "")), "host id")
        if host_id in seen:
            raise FabricError(f"duplicate host id: {host_id}")
        seen.add(host_id)
        if host.get("platform") not in {"macos", "linux", "wsl"}:
            raise FabricError(f"invalid platform for {host_id}")
        if not isinstance(host.get("roles"), list) or not all(isinstance(x, str) for x in host["roles"]):
            raise FabricError(f"invalid roles for {host_id}")
        if not isinstance(host.get("capabilities", []), list):
            raise FabricError(f"invalid capabilities for {host_id}")
        if not isinstance(host.get("priority", 100), int):
            raise FabricError(f"invalid priority for {host_id}")
        runner_priorities = host.get("runner_priorities", {})
        if not isinstance(runner_priorities, dict) or any(key not in RUNNER_ROLES or not isinstance(value, int) for key, value in runner_priorities.items()):
            raise FabricError(f"invalid runner_priorities for {host_id}")
        if host.get("transport", "local") not in {"local", "ssh", "ssh-wsl"}:
            raise FabricError(f"invalid transport for {host_id}")
        command_path = host.get("command_path", [])
        if not isinstance(command_path, list) or not all(isinstance(item, str) and item.startswith("/") and ":" not in item and "\n" not in item for item in command_path):
            raise FabricError(f"invalid command_path for {host_id}")
        if host.get("transport") in {"ssh", "ssh-wsl"}:
            if not host.get("ssh_alias") or not host.get("host_key_fingerprint") or not host.get("known_hosts_file"):
                raise FabricError(f"SSH host {host_id} needs alias, pinned fingerprint, and known_hosts_file")
        if host.get("transport") == "ssh-wsl" and not isinstance(host.get("wsl_distro"), str):
            raise FabricError(f"WSL host {host_id} needs wsl_distro")
    return data


def inventory_identity(data: dict[str, Any]) -> str:
    return digest(data)


def local_capabilities() -> set[str]:
    names = ["git", "python3", "tmux", "orca", "pi", "codex", "claude", "ssh"]
    caps = {name for name in names if shutil.which(name)}
    caps.add("local")
    return caps


def select_host(data: dict[str, Any], runner: str, required: Optional[set[str]] = None, remote: bool = False, host_id: Optional[str] = None) -> dict[str, Any]:
    if runner not in RUNNER_ROLES:
        raise FabricError(f"unsupported runner: {runner}")
    required = set(required or ()) | {runner}
    role = RUNNER_ROLES[runner]
    candidates = []
    for host in data["hosts"]:
        if not host.get("enabled", True):
            continue
        if host_id and host["id"] != host_id:
            continue
        is_remote = host.get("transport", "local") in {"ssh", "ssh-wsl"}
        if is_remote != remote:
            continue
        if role not in host["roles"]:
            continue
        if not required.issubset(set(host.get("capabilities", []))):
            continue
        candidates.append(host)
    if not candidates:
        raise FabricError("no compatible host", 3, "no-compatible-host")
    return sorted(candidates, key=lambda host: (host.get("runner_priorities", {}).get(runner, host.get("priority", 100)), host["id"]))[0]

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .common import FabricError, audit, read_json

STATUS_CODES = {"locked": 6, "unauthenticated": 6, "window_expired": 6, "denied": 6}


def load_manifest(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("entries"), list):
        raise FabricError("secret manifest must be {schema: 1, entries: [...]}")
    for entry in data["entries"]:
        if set(entry) != {"id", "broker_argv", "destination"}:
            raise FabricError("secret entry requires id, broker_argv, destination")
        if not isinstance(entry["broker_argv"], list) or not all(isinstance(x, str) for x in entry["broker_argv"]):
            raise FabricError("broker_argv must be an argument array")
        destination = Path(os.path.expanduser(entry["destination"]))
        home = Path.home().resolve()
        parent = destination.parent.resolve()
        if destination.is_symlink() or (parent != home and home not in parent.parents):
            raise FabricError("secret destination must be a non-symlink inside home", 5, "safety")
        entry["_destination"] = str(destination)
    return data


def check(manifest: dict[str, Any]) -> dict[str, Any]:
    results = []
    for entry in manifest["entries"]:
        completed = subprocess.run([*entry["broker_argv"], "status"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10, check=False)
        status = completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else "error"
        results.append({"id": entry["id"], "status": status, "ready": completed.returncode == 0 and status == "ready"})
    return {"schema": 1, "entries": results, "ready": all(item["ready"] for item in results)}


def provision_local(manifest: dict[str, Any]) -> dict[str, Any]:
    provisioned = []
    for entry in manifest["entries"]:
        destination = Path(entry["_destination"])
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        command = [*entry["broker_argv"], "read", entry["id"]]
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False)
        if completed.returncode != 0:
            raise FabricError(f"broker failed for {entry['id']}", 6, "credential")
        temp = destination.with_name(f".{destination.name}.remote-fabric-{os.getpid()}")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(completed.stdout)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)
        provisioned.append(entry["id"])
        audit("secret-provisioned", item_id=entry["id"], destination_host="local")
    return {"schema": 1, "provisioned": provisioned}

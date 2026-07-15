from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from .common import FabricError, atomic_json, config_root, lock, read_json, state_root


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = read_json(path)
    if not isinstance(manifest, dict) or manifest.get("schema") != 1 or not isinstance(manifest.get("files"), list):
        raise FabricError("deployment manifest must be {schema: 1, files: [...]}")
    for entry in manifest["files"]:
        if set(entry) != {"source", "destination"}:
            raise FabricError("deployment entries require only source and destination")
        source = Path(entry["source"])
        destination = Path(os.path.expandvars(os.path.expanduser(entry["destination"])))
        if not source.is_absolute():
            source = path.parent / source
        if not source.is_file():
            raise FabricError(f"managed source missing: {source}")
        home = Path.home().resolve()
        if destination.is_symlink() or destination == Path.home() or home not in destination.parent.resolve().parents and destination.parent.resolve() != home:
            raise FabricError(f"destination must be a non-symlink inside home: {destination}", 5, "safety")
        entry["_source"] = str(source.resolve())
        entry["_destination"] = str(destination)
    return manifest


def _hash(path: Path) -> Optional[str]:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def plan(manifest: dict[str, Any]) -> dict[str, Any]:
    changes = []
    for entry in manifest["files"]:
        source, destination = Path(entry["_source"]), Path(entry["_destination"])
        before, after = _hash(destination), _hash(source)
        if before != after:
            changes.append({"destination": str(destination), "before": before, "after": after})
    return {"schema": 1, "changes": changes, "changed": bool(changes)}


def apply(manifest: dict[str, Any]) -> dict[str, Any]:
    desired = plan(manifest)
    if not desired["changed"]:
        return {**desired, "generation": None}
    generation = f"{time.time_ns()}"
    backup = state_root() / "backups" / generation
    with lock("host/local", "reconcile-apply", timeout=30):
        for entry in manifest["files"]:
            source, destination = Path(entry["_source"]), Path(entry["_destination"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            relative = destination.relative_to(Path.home())
            if destination.exists():
                target = backup / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, target)
            temp = destination.with_name(f".{destination.name}.remote-fabric-{os.getpid()}")
            shutil.copy2(source, temp)
            os.replace(temp, destination)
        record = {"schema": 1, "generation": generation, "backup": str(backup), "destinations": [entry["_destination"] for entry in manifest["files"]]}
        atomic_json(state_root() / "deployments" / f"{generation}.json", record)
        atomic_json(state_root() / "deployments/current.json", record)
    return {**desired, "generation": generation}


def rollback(generation: str) -> dict[str, Any]:
    record = read_json(state_root() / "deployments" / f"{generation}.json")
    backup = Path(record["backup"])
    restored = []
    with lock("host/local", "reconcile-rollback", timeout=30):
        for raw in record["destinations"]:
            destination = Path(raw)
            saved = backup / destination.relative_to(Path.home())
            if saved.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, destination)
                restored.append(str(destination))
            elif destination.exists():
                destination.unlink()
                restored.append(str(destination))
        atomic_json(state_root() / "deployments/rollback.json", {"schema": 1, "from": generation, "restored": restored, "at": time.time()})
    return {"schema": 1, "generation": generation, "restored": restored}

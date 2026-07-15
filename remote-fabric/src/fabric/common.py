from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
SCHEMA_VERSION = 1


class FabricError(RuntimeError):
    def __init__(self, message: str, code: int = 2, category: str = "invalid") -> None:
        super().__init__(message)
        self.code = code
        self.category = category


def require_id(value: str, label: str = "id") -> str:
    if not ID_RE.fullmatch(value):
        raise FabricError(f"invalid {label}: {value!r}")
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def state_root() -> Path:
    root = Path(os.environ.get("REMOTE_FABRIC_STATE", os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")))
    if root.name != "remote-fabric" and "REMOTE_FABRIC_STATE" not in os.environ:
        root /= "remote-fabric"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def config_root() -> Path:
    override = os.environ.get("REMOTE_FABRIC_CONFIG")
    if override:
        return Path(override)
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "remote-fabric"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists() and default is not None:
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise FabricError(f"cannot read JSON {path}: {exc}") from exc


def atomic_json(path: Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temp.unlink(missing_ok=True)


def audit(event: str, **fields: Any) -> Path:
    forbidden = {"secret", "token", "password", "credential", "prompt", "response"}
    if forbidden.intersection(k.lower() for k in fields):
        raise FabricError("refusing potentially sensitive audit fields", 5, "safety")
    now = time.time_ns()
    record = {
        "schema": SCHEMA_VERSION,
        "id": str(uuid.uuid4()),
        "time_ns": now,
        "event": event,
        **fields,
    }
    folder = state_root() / "audit/events"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f"{now:020d}-{record['id']}.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical(record) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path


@contextmanager
def lock(key: str, operation: str, timeout: float = 15.0) -> Iterator[dict[str, Any]]:
    safe = "/".join(require_id(part, "lock component") for part in key.split("/"))
    path = state_root() / "locks" / f"{safe}.lock"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    owner = {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "operation": operation,
        "started_ns": time.time_ns(),
        "token": uuid.uuid4().hex,
    }
    deadline = time.monotonic() + timeout
    while True:
        try:
            path.mkdir()
            atomic_json(path / "owner.json", owner)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise FabricError(f"lock busy: {key}", 5, "locked")
            time.sleep(0.025)
    try:
        yield owner
    finally:
        try:
            recorded = read_json(path / "owner.json")
            if recorded.get("token") != owner["token"]:
                raise FabricError(f"lock ownership changed: {key}", 5, "locked")
            (path / "owner.json").unlink()
            path.rmdir()
        except FileNotFoundError:
            raise FabricError(f"lock disappeared: {key}", 5, "locked")

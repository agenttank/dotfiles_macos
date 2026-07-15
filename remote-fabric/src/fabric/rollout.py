from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from .common import FabricError, atomic_json, digest, lock, read_json, state_root

GATES = (
    "cold_boot",
    "credential_expiry",
    "network_interruption",
    "concurrent_worktrees",
    "real_provider_calls",
    "wsl_lifecycle",
    "orca_restart",
    "secret_leak_checks",
    "local_fallback",
)
SOAK_SECONDS = 168 * 3600
MAX_GAP_SECONDS = 15 * 60


def evidence_dir() -> Path:
    return state_root() / "evidence"


def record_evidence(gate: str, passed: bool, identity: str, observed_at: Optional[float] = None, details: Optional[dict[str, Any]] = None) -> Path:
    if gate not in GATES and gate != "soak_heartbeat":
        raise FabricError(f"unknown rollout gate: {gate}")
    observed = observed_at if observed_at is not None else time.time()
    record = {"schema": 1, "gate": gate, "passed": bool(passed), "identity": identity, "observed_at": observed, "details": details or {}}
    folder = evidence_dir() / gate
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f"{int(observed * 1_000_000):020d}-{digest(record)[:12]}.json"
    atomic_json(path, record)
    return path


def _records(gate: str) -> list[dict[str, Any]]:
    folder = evidence_dir() / gate
    if not folder.exists():
        return []
    return [read_json(path) for path in sorted(folder.glob("*.json"))]


def evaluate(identity: str, now: Optional[float] = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    gate_status: dict[str, bool] = {}
    receipts: dict[str, str] = {}
    for gate in GATES:
        matching = [r for r in _records(gate) if r.get("identity") == identity and r.get("passed") is True]
        gate_status[gate] = bool(matching)
        if matching:
            receipts[gate] = digest(matching[-1])
    heartbeats = [r for r in _records("soak_heartbeat") if r.get("identity") == identity and r.get("passed") is True]
    times = sorted(float(r["observed_at"]) for r in heartbeats)
    duration = times[-1] - times[0] if len(times) >= 2 else 0
    max_gap = max((b - a for a, b in zip(times, times[1:])), default=float("inf"))
    soak = bool(times) and duration >= SOAK_SECONDS and max_gap <= MAX_GAP_SECONDS and now - times[-1] <= MAX_GAP_SECONDS
    accepted = all(gate_status.values()) and soak
    result = {
        "schema": 1,
        "identity": identity,
        "accepted": accepted,
        "gates": gate_status,
        "evidence_receipts": receipts,
        "soak": {"passed": soak, "duration_seconds": duration, "max_gap_seconds": None if max_gap == float("inf") else max_gap, "required_seconds": SOAK_SECONDS},
        "evaluated_at": now,
    }
    with lock("rollout/local", "rollout-evaluate"):
        atomic_json(state_root() / "rollout/acceptance-v1.json", result)
    return result


def acceptance(identity: str) -> bool:
    path = state_root() / "rollout/acceptance-v1.json"
    if not path.exists():
        return False
    record = read_json(path)
    return record.get("identity") == identity and record.get("accepted") is True


def routing() -> dict[str, Any]:
    return read_json(state_root() / "rollout/routing.json", {"schema": 1, "remote_default": False})


def set_remote_default(enabled: bool, identity: str) -> dict[str, Any]:
    if enabled and not acceptance(identity):
        raise FabricError("remote default blocked until all rollout gates and soak pass", 10, "rollout-blocked")
    value = {"schema": 1, "remote_default": bool(enabled), "identity": identity if enabled else None, "updated_at": time.time()}
    with lock("rollout/local", "routing-update"):
        atomic_json(state_root() / "rollout/routing.json", value)
    return value

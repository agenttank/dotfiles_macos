from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .common import FabricError, atomic_json, audit, digest, lock, read_json, require_id, state_root


def _git(path: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(path), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
    if completed.returncode != 0:
        raise FabricError(f"git precondition failed: {' '.join(args)}", 5, "repository")
    return completed.stdout.strip()


def load_config(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("repositories"), list):
        raise FabricError("repository config must be {schema: 1, repositories: [...]}")
    seen = set()
    for repo in data["repositories"]:
        repo_id = require_id(str(repo.get("id", "")), "repo id")
        if repo_id in seen:
            raise FabricError(f"duplicate repository id: {repo_id}")
        seen.add(repo_id)
        if not isinstance(repo.get("origin"), str) or not repo["origin"]:
            raise FabricError(f"repository {repo_id} needs origin")
        for key in ("canonical_path", "worktree_root"):
            value = Path(str(repo.get(key, ""))).expanduser()
            home = Path.home().resolve()
            parent = value.parent.resolve()
            if value.is_symlink() or (parent != home and home not in parent.parents):
                raise FabricError(f"{key} must be a non-symlink inside home", 5, "safety")
            repo[f"_{key}"] = str(value)
    return data


def prepare(config: dict[str, Any], repo_id: str, ref: str, work_id: str) -> dict[str, Any]:
    require_id(repo_id, "repo id")
    require_id(work_id, "work id")
    if not ref or ref.startswith("-") or any(ch.isspace() or ch == "\0" for ch in ref):
        raise FabricError("invalid Git ref")
    repo = next((item for item in config["repositories"] if item["id"] == repo_id), None)
    if not repo:
        raise FabricError(f"unknown repository: {repo_id}")
    canonical = Path(repo["_canonical_path"])
    target = Path(repo["_worktree_root"]) / repo_id / work_id
    with lock(f"work/local/{repo_id}/{work_id}", "repo-prepare", timeout=30):
        if not canonical.exists():
            canonical.parent.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(["git", "clone", "--no-checkout", "--", repo["origin"], str(canonical)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, check=False)
            if completed.returncode != 0:
                raise FabricError("canonical clone failed", 7, "repository")
        actual_origin = _git(canonical, "remote", "get-url", "origin")
        if actual_origin != repo["origin"]:
            raise FabricError("canonical origin mismatch", 5, "repository")
        _git(canonical, "fetch", "--prune", "--", "origin", ref)
        sha = _git(canonical, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
        if target.exists():
            if _git(target, "rev-parse", "HEAD") != sha:
                raise FabricError("existing worktree metadata mismatch", 5, "collision")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(["git", "-C", str(canonical), "worktree", "add", "--detach", "--", str(target), sha], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
            if completed.returncode != 0:
                raise FabricError("worktree creation failed", 7, "repository")
        receipt = {"schema": 1, "repo": repo_id, "work_id": work_id, "sha": sha, "path": str(target), "origin": repo["origin"]}
        atomic_json(state_root() / "receipts/repositories" / f"{repo_id}-{work_id}.json", receipt)
        audit("repository-prepared", repo=repo_id, work_id=work_id, sha=sha)
        return receipt


def handoff_check(path: Path, target: str) -> dict[str, Any]:
    require_id(target, "target host")
    root = Path(_git(path, "rev-parse", "--show-toplevel"))
    if _git(root, "status", "--porcelain"):
        raise FabricError("handoff requires a clean worktree", 5, "dirty-worktree")
    sha = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    remotes = _git(root, "remote").splitlines()
    if not remotes:
        raise FabricError("handoff requires a configured remote", 5, "repository")
    upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    ahead = int(_git(root, "rev-list", "--count", f"{upstream}..HEAD"))
    if ahead:
        raise FabricError("handoff requires all commits pushed", 5, "unpushed")
    receipt = {"schema": 1, "source_path": str(root), "target": target, "sha": sha, "branch": branch, "remote": remotes[0]}
    receipt["id"] = digest(receipt)[:24]
    atomic_json(state_root() / "receipts/handoffs" / f"{receipt['id']}.json", receipt)
    audit("handoff-ready", receipt_id=receipt["id"], target=target, sha=sha)
    return receipt

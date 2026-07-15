# Architecture

The controller reads a non-secret inventory, validates identity/capability declarations, chooses deterministically, and invokes existing host tools over pinned OpenSSH. macOS/Linux hosts execute directly; WSL can use a pinned Windows OpenSSH relay that forwards an encoded PowerShell argument array to `wsl.exe --exec`, avoiding a second SSH/Tailscale daemon inside WSL. Durable work lives in tmux; a session receipt pins host, metadata, URI, and attach argv. State uses XDG paths, atomic replacement, immutable events, and per-resource mkdir locks.

Trust boundaries:

1. Git stores implementation, sample inventory, and non-secret desired config.
2. SSH authenticates transport against a dedicated known-hosts file and declared fingerprint.
3. Each destination authenticates to its own secret broker and provider; values never cross the controller boundary.
4. Git commits/refs transfer work. Dirty or unpushed worktrees cannot be handed off.
5. Rollout evidence controls routing. Documentation or a manually edited boolean cannot enable remote default.

Failures are explicit: invalid/config=2, no host=3, transport/identity=4, lock/safety=5, credential=6, reconcile=7, runner=8, partial rollback=9, rollout blocked=10.

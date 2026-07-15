# Threat model

Protected assets are provider credentials, SSH identity, source history, uncommitted work, session ownership, and rollout evidence.

Controls:

- reject secret-like inventory keys; keep secret manifests host-local;
- broker values use stdout only inside the destination process, are written `0600`, and are never audited;
- all subprocesses use argv arrays; the one unavoidable SSH remote shell string is produced with `shlex.join` from validated IDs and fixed commands;
- require a dedicated known-hosts file whose fingerprint matches inventory before SSH;
- bound SSH/broker/runner calls with timeouts and disable interactive SSH auth;
- refuse dirty/unpushed handoff and destructive Git/mirroring operations;
- serialize resource mutation, use owner-token locks, and atomically persist receipts;
- keep remote opt-in and never silently fall back;
- bind acceptance to release/inventory identity and continuous soak evidence.

Out of scope: compromise of the controller, destination OS, external broker, provider, Git remote, or SSH implementation. Such compromise invalidates the trust boundary and requires credential rotation plus new rollout evidence.

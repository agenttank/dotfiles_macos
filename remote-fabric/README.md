# Remote Fabric

A dependency-light, agentless execution layer for Orca and Pi. The MacBook remains a thin control terminal; an SSH-reachable Mac can host Orca sessions and Ubuntu/WSL can host Pi/build sessions. WSL can use the Windows OpenSSH relay through the `ssh-wsl` transport, forwarding an encoded PowerShell argument array to `wsl.exe --exec` without requiring a second SSH/Tailscale daemon inside WSL. The implementation uses existing SSH, Git, tmux, Orca, and provider CLIs—there is no fabric daemon.

## Safety defaults

- Execution is **local by default**. Remote starts require `--remote` until `rollout evaluate` proves every operational gate and the 168-hour soak.
- A remote failure never silently runs locally. `--local` and `routing disable-remote-default` are offline operations.
- Inventory/config are non-secret. SSH identity is pinned through a dedicated known-hosts file and fingerprint check.
- Provider material is fetched by a broker on the destination host. Values are never accepted as CLI arguments and never enter receipts/audit output.
- Runtime state is under `${XDG_STATE_HOME:-~/.local/state}/remote-fabric`, not in Git.
- Git handoff requires a clean, pushed commit. The fabric never mirrors a worktree, copies `.git`, resets, cleans, or automatically deletes source worktrees.

## Quick start

```sh
cp remote-fabric/inventory/hosts.json ~/.config/remote-fabric/hosts.json
# Replace host aliases/fingerprints, create the dedicated known_hosts file, then enable hosts.
remote-fabric/bin/fabric --json inventory validate
remote-fabric/bin/fabric --json probe --host mac-mini --remote
remote-fabric/bin/fabric --json session start --runner pi --repo my-repo --ref <sha> --work-id TG-55 --remote --dry-run
remote-fabric/bin/fabric --json session attach --work-id TG-55 --dry-run
```

Global `--json` and `--inventory` options precede the subcommand. `--dry-run` returns exact launch/attach argument arrays without executing them.

## Staged rollout during soak

Remote work may start explicitly before the soak completes while the MacBook keeps the local repository and fallback path:

```sh
fabric session start --runner orca --repo <repo> --ref <pushed-sha> --work-id <id> --remote
fabric session start --runner pi    --repo <repo> --ref <pushed-sha> --work-id <id> --remote
fabric session start --runner build --repo <repo> --ref <pushed-sha> --work-id <id> --remote
fabric session attach --work-id <id>
```

Inventory priorities route Orca to the Mac mini and Pi/build to Windows WSL. Use clean, pushed commits or Git bundles as checkpoints because uncommitted remote edits are not present in the MacBook clone. Keep `remote_default=false`; use `--local` explicitly whenever the remote path is unavailable.

## Commands

```text
inventory validate|list
probe [--host HOST --remote]
select --runner orca|pi|build [--requires CAP,...] [--remote]
reconcile plan|apply [--manifest FILE]
reconcile rollback --generation ID
secrets check|provision --manifest HOST_LOCAL_FILE
repo prepare --config FILE --repo ID --ref REF --work-id ID
handoff check --path WORKTREE --target HOST
session start|locate|attach ...
routing status|enable-remote-default|disable-remote-default
rollout status|evaluate|record --gate GATE --passed
health --all
canary transport|repository|provider --host HOST --remote
audit show [--jsonl]
```

`session start` deterministically selects by numeric priority then host ID. Its atomic receipt pins the host and stable `fabric://session/<id>` URI; attach never selects again. Same-work concurrent starts serialize through a portable mkdir lock and converge on one receipt.

## Bootstrap and reconciliation

Bootstrap adapters are explicit validation/reconciliation entry points:

```sh
remote-fabric/bootstrap/macos.sh plan
remote-fabric/bootstrap/macos.sh validate
remote-fabric/bootstrap/ubuntu.sh validate
remote-fabric/bootstrap/wsl-guest.sh validate
pwsh -File remote-fabric/bootstrap/windows-wsl.ps1 -Distro Ubuntu -Plan
```

On Windows, `-Apply` installs an S4U startup task plus a one-minute watchdog trigger that keeps or recovers the distro without an interactive login. `-LoopbackForwardPort 3456` additionally maintains a Windows-loopback-only portproxy to the current WSL address; use it only when the guest intentionally exposes the approved provider endpoint on that port. `-LanRecoverySubnet 192.168.1.0/24` optionally installs a source-restricted LAN SSH recovery rule so a trusted peer can restore Tailscale without exposing SSH beyond that subnet.

They do not install packages implicitly. `reconcile plan` is read-only; `apply` copies only manifest-owned files, records a generation, and is a no-op when hashes already match. `rollback` restores generation backups. Remote deployment should invoke these exact commands through the SSH transport after deploying a pinned Git release.

## Pi through Meridian

After Meridian is healthy on `127.0.0.1:3456`, install Pi's non-secret provider configuration and the required request-filter/profile-autoswitch extensions:

```sh
remote-fabric/bootstrap/pi-meridian.sh plan
remote-fabric/bootstrap/pi-meridian.sh apply
remote-fabric/bootstrap/pi-meridian.sh validate
```

The system-prompt filter is required for subscription-backed requests; without it Anthropic classifies Pi's stock prompt as a third-party app and charges extra usage. The autoswitch extension adds `x-meridian-profile` from fresh quota data and coordinates concurrent Pi processes through atomic local lease state. Credentials remain outside this repository and outside the script.

## Secret broker contract

`secret-manifest.example.json` contains only item IDs, broker argv, and destination paths. On each destination host, `secrets provision` invokes `BROKER status/read ITEM`, captures the value only in memory, atomically writes mode `0600`, discards broker stderr, and emits metadata-only audit events. For remote hosts, execute `fabric secrets ...` *on that host*; the controller must never fetch then forward provider values.

## State, locking, and audit

State/lock directories are mode `0700`; JSON state is written temp → fsync → replace → directory fsync. Locks are atomic directories with owner tokens and are never automatically broken. Audit events are immutable, exclusive files rather than concurrent JSONL appends; `audit show --jsonl` is an ordered projection.

## Verification

```sh
make -C remote-fabric check
make -C remote-fabric test
```

Local tests cover deterministic selection, malformed/secret-bearing inventory, atomic/audit contention, same-work concurrent session starts, remote-no-fallback, rollout identity/soak enforcement, idempotent reconcile/rollback, and seeded-secret leak prevention. CI runs Python/shell checks on macOS and Ubuntu and PowerShell parsing on Windows.

See [`docs/acceptance-matrix.md`](docs/acceptance-matrix.md) before changing the default workflow. Real hosts, providers, restarts, and soak evidence are deliberately not claimed by this repository-only test suite.

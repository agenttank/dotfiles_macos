# Rollout acceptance matrix

Remote execution remains opt-in until `fabric rollout evaluate` writes an acceptance record for the current release + inventory identity and `routing enable-remote-default` succeeds. Evidence is operational state, never committed.

| Scenario | Pass condition | Automated here | Operational status |
|---|---|---:|---|
| Cold boot | MacBook reaches Mac mini and WSL; declared services become healthy without repair. | Partial probe simulation | **Pending** real cold boot |
| Credential expiry | Stable auth failure, no leak/fallback; destination reprovision restores canary. | Fake broker | **Pending** real broker/provider |
| Network interruption | Work survives; attach fails within timeout then reuses the same receipt after recovery. | Remote-no-fallback contract | **Pending** Tailscale interruption |
| Concurrent worktrees | Different IDs isolate; same ID converges; unsafe collisions fail closed. | 24-way session contention | **Pending** cross-host smoke |
| Real provider calls | Cost-bounded Pi/build and Codex/Claude canaries run on intended hosts with redacted audit. | No | **Pending** explicit paid canaries |
| WSL lifecycle | Windows restart starts distro/services; Linux-filesystem worktree is reachable. | Script/static CI validation | **Pending** Windows restart |
| Orca restart | tmux workload and fabric URI survive; Orca attachment can be recreated. | Receipt contract | **Pending** Orca restart |
| Secret leaks | Seed values absent from Git, argv, stdout/stderr, state, receipts, and audit. | Seeded-value scan | **Pending** real auth-file scan |
| Seven-day soak | At least 168 hours of matching-identity heartbeats, no gap >15 minutes, no safety failure. | Time-model evaluator | **Pending** 168-hour run |
| Local fallback | Local works offline; remote failure does not fall back; remote default can be disabled offline. | Yes | **Pending** operator smoke |

## Evidence workflow

Record only after independently verifying a gate:

```sh
fabric --json rollout record --gate cold_boot --passed
fabric --json rollout record --gate soak_heartbeat --passed
fabric --json rollout evaluate
fabric --json routing enable-remote-default
```

Evidence is bound to the computed identity. A release or inventory change makes prior acceptance stale. `record` cannot directly set acceptance; the evaluator derives it from all required receipts and heartbeat continuity.

## Go/no-go

**NO-GO** while any Operational status above is Pending. A repository PR can complete the implementation and automated matrix, but cannot truthfully complete cold boots, real credentials/providers, lifecycle restarts, or a seven-day soak. Keep `remote_default=false`; use explicit `--remote` for canaries and preserve the local path.

---
name: remote-fabric
description: Select, launch, locate, attach to, health-check, or reconcile Orca/Pi/build sessions through the repository's remote-fabric CLI. Use when work should run on the Mac mini or Ubuntu/WSL worker, or when checking remote rollout readiness.
---

# Remote Fabric

The CLI is the source of truth. Do not implement SSH, host selection, Git transfer, secret retrieval, session naming, fallback, or rollout logic in prompts.

From the repository root:

```sh
remote-fabric/bin/fabric --json inventory validate
remote-fabric/bin/fabric --json health --all
remote-fabric/bin/fabric --json session start --runner pi --repo REPO --ref COMMIT --work-id WORK --remote
remote-fabric/bin/fabric --json session locate --work-id WORK
remote-fabric/bin/fabric session attach --work-id WORK
```

Rules:

- Use `--remote` only when the user requests offload; otherwise local remains the default.
- Never retry a remote failure locally without explicit user direction.
- Never copy `.git`, raw auth files, provider config, tokens, or broker output.
- Handoff only a clean, pushed commit after `handoff check` succeeds.
- Treat exit 10 as a rollout-policy block, not an instruction to bypass acceptance.
- For credentials, run `secrets check/provision` on the destination host. Never fetch values on the controller.
- Return the stable `fabric://session/...` URI from the receipt; attach must use the receipt rather than selecting again.

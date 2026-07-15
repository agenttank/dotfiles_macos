from __future__ import annotations

import base64
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Sequence

from .common import FabricError


def remote_argv(host: dict[str, Any], argv: Sequence[str]) -> list[str]:
    command_path = host.get("command_path", [])
    if command_path:
        return ["env", f"PATH={':'.join(command_path)}", *argv]
    return list(argv)


def remote_command(host: dict[str, Any], argv: Sequence[str]) -> str:
    command = remote_argv(host, argv)
    if host.get("transport") == "ssh-wsl":
        distro = host.get("wsl_distro")
        if not isinstance(distro, str) or not distro:
            raise FabricError(f"WSL distro missing for {host['id']}")
        values = ["--distribution", distro, "--exec", *command]
        quoted = ",".join("'" + value.replace("'", "''") + "'" for value in values)
        script = f"$a=@({quoted}); & wsl.exe @a; exit $LASTEXITCODE"
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        return f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded}"
    return shlex.join(command)


def ssh_base(host: dict[str, Any]) -> list[str]:
    known = Path(os.path.expanduser(host.get("known_hosts_file", "")))
    expected = host.get("host_key_fingerprint", "")
    if not known.is_file():
        raise FabricError(f"pinned known-hosts file missing for {host['id']}", 4, "identity")
    check = subprocess.run(["ssh-keygen", "-lf", str(known)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False)
    fingerprints = {line.split()[1] for line in check.stdout.splitlines() if len(line.split()) >= 2}
    if check.returncode != 0 or expected not in fingerprints:
        raise FabricError(f"host fingerprint mismatch for {host['id']}", 4, "identity")
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known}",
        "-o", "ConnectTimeout=8",
        host["ssh_alias"],
    ]

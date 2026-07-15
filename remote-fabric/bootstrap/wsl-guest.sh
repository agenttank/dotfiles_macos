#!/bin/sh
set -eu
. "$(dirname "$0")/common.sh"

case "$mode" in
  plan) echo 'validate WSL systemd sshd tailscale and Linux-local repository roots' ;;
  apply|validate)
    validate_common
    grep -qi microsoft /proc/sys/kernel/osrelease || { echo 'not WSL' >&2; exit 7; }
    if [ "${REMOTE_FABRIC_RELAY:-}" = windows-ssh ]; then
      echo 'WSL guest ready through Windows SSH relay'
      exit 0
    fi
    [ "$(ps -p 1 -o comm= | tr -d ' ')" = systemd ] || { echo 'systemd is not PID 1' >&2; exit 7; }
    systemctl is-active --quiet ssh || systemctl is-active --quiet sshd || { echo 'sshd inactive' >&2; exit 7; }
    command -v tailscale >/dev/null 2>&1 || { echo 'tailscale missing' >&2; exit 7; }
    echo 'WSL guest ready'
    ;;
esac

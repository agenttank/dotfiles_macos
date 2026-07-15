#!/bin/sh
set -eu

PATH="$HOME/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PATH

mode=${1:-plan}
case "$mode" in plan|apply|validate) ;; *) echo "usage: $0 plan|apply|validate" >&2; exit 2;; esac

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing capability: $1" >&2; return 1; }; }
validate_common() { need git; need python3; need ssh; need tmux; }

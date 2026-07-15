#!/bin/sh
set -eu
. "$(dirname "$0")/common.sh"

case "$mode" in
  plan) echo 'validate git python3 ssh tmux; no changes planned' ;;
  apply|validate) validate_common; [ "$(uname -s)" = Darwin ] || { echo 'not macOS' >&2; exit 7; }; echo 'macOS capabilities ready' ;;
esac

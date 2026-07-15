#!/bin/sh
set -eu
. "$(dirname "$0")/common.sh"

case "$mode" in
  plan) echo 'validate git python3 ssh tmux; no package changes are implicit' ;;
  apply|validate) validate_common; [ "$(uname -s)" = Linux ] || { echo 'not Linux' >&2; exit 7; }; echo 'Linux capabilities ready' ;;
esac

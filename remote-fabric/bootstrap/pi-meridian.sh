#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-plan}"
ENDPOINT="${PI_MERIDIAN_ENDPOINT:-http://127.0.0.1:3456}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
EXTENSIONS_DIR="$AGENT_DIR/extensions"
SOURCE_DIR="$ROOT/pi/extensions"

case "$ACTION" in
  plan)
    printf '{"schema":1,"action":"plan","endpoint":"%s","agent_dir":"%s"}\n' "$ENDPOINT" "$AGENT_DIR"
    ;;
  apply)
    install -d -m 0700 "$AGENT_DIR" "$EXTENSIONS_DIR" "$EXTENSIONS_DIR/meridian-profile-autoswitch"
    install -m 0644 "$SOURCE_DIR/meridian-system-prompt-filter.ts" "$EXTENSIONS_DIR/meridian-system-prompt-filter.ts"
    install -m 0644 "$SOURCE_DIR/meridian-profile-autoswitch/index.ts" "$EXTENSIONS_DIR/meridian-profile-autoswitch/index.ts"
    install -m 0644 "$SOURCE_DIR/meridian-profile-autoswitch/coordinator.ts" "$EXTENSIONS_DIR/meridian-profile-autoswitch/coordinator.ts"
    install -m 0644 "$SOURCE_DIR/meridian-profile-autoswitch/policy.ts" "$EXTENSIONS_DIR/meridian-profile-autoswitch/policy.ts"
    python3 - "$AGENT_DIR/models.json" "$ENDPOINT" <<'PY'
import json
import os
import sys
import tempfile

path, endpoint = sys.argv[1:]
try:
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
except FileNotFoundError:
    config = {}
providers = config.setdefault("providers", {})
providers["anthropic"] = {
    "name": "Anthropic via Meridian",
    "baseUrl": endpoint,
    "apiKey": "x",
    "headers": {"x-meridian-agent": "pi"},
}
os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=".models.", suffix=".tmp", dir=os.path.dirname(path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
    rm -rf "$HOME/.cache/pi-meridian-autoswitch"
    "$0" validate
    ;;
  validate)
    test -f "$EXTENSIONS_DIR/meridian-system-prompt-filter.ts"
    test -f "$EXTENSIONS_DIR/meridian-profile-autoswitch/index.ts"
    python3 - "$AGENT_DIR/models.json" "$ENDPOINT" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    provider = json.load(handle)["providers"]["anthropic"]
assert provider["baseUrl"] == sys.argv[2]
assert provider["headers"]["x-meridian-agent"] == "pi"
PY
    printf '{"schema":1,"action":"validate","ready":true}\n'
    ;;
  *)
    echo "usage: $0 {plan|apply|validate}" >&2
    exit 2
    ;;
esac

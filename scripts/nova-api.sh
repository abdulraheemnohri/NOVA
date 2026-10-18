#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TOKEN_FILE="${NOVA_API_TOKEN_FILE:-$ROOT/data/api.token}"
METHOD="${1:-GET}"
API_PATH="${2:-}"
BODY="${3:-}"

if [[ -z "$API_PATH" || "$API_PATH" != /api/* ]]; then
  echo "Usage: bash scripts/nova-api.sh METHOD /api/path [JSON_BODY|-]" >&2
  echo "Only /api/* endpoints are allowed." >&2
  exit 2
fi
if [[ ! -r "$TOKEN_FILE" ]]; then
  echo "NOVA API token file is missing or unreadable: $TOKEN_FILE" >&2
  echo "Start NOVA once to generate it, or set NOVA_API_TOKEN_FILE." >&2
  exit 2
fi

METHOD="${METHOD^^}"
case "$METHOD" in
  GET|POST|PUT|DELETE) ;;
  *) echo "Allowed methods: GET, POST, PUT, DELETE." >&2; exit 2 ;;
esac

if [[ "$BODY" == "-" ]]; then
  BODY="$(cat)"
fi

NOVA_API_TOKEN="$(<"$TOKEN_FILE")" python3 - "$METHOD" "$API_PATH" "$BODY" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

method, api_path, body_text = sys.argv[1:4]
token = os.environ.get("NOVA_API_TOKEN", "").strip()
base = os.environ.get("NOVA_API_BASE", "http://127.0.0.1:8000").rstrip("/")
parsed_base = urllib.parse.urlsplit(base)
if (
    parsed_base.scheme != "http"
    or parsed_base.hostname not in {"127.0.0.1", "localhost", "::1"}
    or parsed_base.username is not None
    or parsed_base.password is not None
    or parsed_base.path not in {"", "/"}
    or parsed_base.query
    or parsed_base.fragment
):
    print("NOVA_API_BASE must be a plain HTTP loopback URL.", file=sys.stderr)
    raise SystemExit(2)

parsed_path = urllib.parse.urlsplit(api_path)
if (
    not api_path.startswith("/api/")
    or parsed_path.netloc
    or any(part == ".." for part in parsed_path.path.split("/"))
):
    print("Only normalized /api/* paths are allowed.", file=sys.stderr)
    raise SystemExit(2)
if not token:
    print("NOVA API token file is empty.", file=sys.stderr)
    raise SystemExit(2)

headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
data = None
if method in {"POST", "PUT"}:
    if body_text:
        try:
            json.loads(body_text)
        except json.JSONDecodeError as exc:
            print(f"Request body must be valid JSON: {exc.msg}", file=sys.stderr)
            raise SystemExit(2) from exc
        data = body_text.encode("utf-8")
    else:
        data = b"{}"
    headers["Content-Type"] = "application/json"

request = urllib.request.Request(
    base + api_path,
    data=data,
    headers=headers,
    method=method,
)
try:
    with urllib.request.urlopen(request, timeout=120) as response:
        output = response.read(5_000_001)
        if len(output) > 5_000_000:
            print("API response exceeded 5 MB; output suppressed.", file=sys.stderr)
            raise SystemExit(1)
        sys.stdout.write(output.decode("utf-8", errors="replace"))
        if output and not output.endswith(b"\n"):
            sys.stdout.write("\n")
        print(f"HTTP {response.status}", file=sys.stderr)
except urllib.error.HTTPError as exc:
    output = exc.read(1_000_000)
    if output:
        sys.stdout.write(output.decode("utf-8", errors="replace") + "\n")
    print(f"HTTP {exc.code}", file=sys.stderr)
    raise SystemExit(22)
except (urllib.error.URLError, TimeoutError) as exc:
    print(f"API request failed: {exc}", file=sys.stderr)
    raise SystemExit(7)
PY

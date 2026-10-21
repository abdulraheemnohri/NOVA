"""Minimal JSON-RPC MCP fixture for runtime tests."""
import json
import sys

for line in sys.stdin:
    try:
        message = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        continue
    if "id" not in message:
        continue
    method = message.get("method")
    if method == "initialize":
        result = {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1"},
        }
    elif method == "tools/list":
        result = {"tools": [
            {"name": "read_info", "description": "Read-only fixture", "annotations": {"readOnlyHint": True}},
            {"name": "write_info", "description": "Mutating fixture", "annotations": {"readOnlyHint": False}},
        ]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "called:" + message["params"]["name"]}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Method not found"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)

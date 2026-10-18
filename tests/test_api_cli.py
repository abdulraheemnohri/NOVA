import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "nova-api.sh"
TOKEN = "test-token-that-must-not-leak"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send_error(401)
            return
        body = json.dumps({"ok": True, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


def _run(tmp_path, server_url, *args):
    token_file = tmp_path / "api.token"
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    env = os.environ.copy()
    env["NOVA_API_TOKEN_FILE"] = str(token_file)
    env["NOVA_API_BASE"] = server_url
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def test_api_helper_reads_token_and_sends_authenticated_request(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        result = _run(tmp_path, url, "GET", "/api/settings/preferences")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"ok": True, "path": "/api/settings/preferences"}
    assert "HTTP 200" in result.stderr
    assert TOKEN not in result.stdout
    assert TOKEN not in result.stderr


def test_api_helper_rejects_non_loopback_base(tmp_path):
    result = _run(tmp_path, "http://example.com:8000", "GET", "/api/health")
    assert result.returncode == 2
    assert "loopback" in result.stderr
    assert TOKEN not in result.stderr


def test_api_helper_rejects_paths_outside_api_prefix(tmp_path):
    result = _run(tmp_path, "http://127.0.0.1:8000", "GET", "https://example.com")
    assert result.returncode == 2
    assert "Only /api/* endpoints" in result.stderr

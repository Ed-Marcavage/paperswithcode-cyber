"""Check secret boundaries without loading .local.env or invoking Docker.

The proxy integration check runs only when an unprivileged nginx is installed.
"""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import yaml

from deploy.nginx_validate import location_block

ROOT = Path(__file__).resolve().parents[3]


def test_compose_keeps_key_backend_only_and_upstream_chat_disabled():
    services = yaml.safe_load((ROOT / "local-dev/compose.yaml").read_text())["services"]
    backend = services["backend"]["environment"]
    assert backend["PWC_ASSISTANT_API_KEY"] == "${PWC_ASSISTANT_API_KEY:-}"
    assert backend["PWC_ASSISTANT_ENABLED"] == "${PWC_ASSISTANT_ENABLED:-false}"
    assert backend["PWC_ASSISTANT_STORE_ANALYTICS_SESSION"] == "false"
    for service in ("frontend", "mcp"):
        assert "env_file" not in services[service]
        assert "ASSISTANT_API_KEY" not in str(services[service])
    frontend = services["frontend"]["environment"]
    assert frontend["VITE_CHAT_ENABLED"] == "false"
    assert frontend["VITE_ASSISTANT_ENABLED"] == "${VITE_ASSISTANT_ENABLED:-false}"
    assert "mcp:7860" in services["mcp"]["environment"]["PWC_MCP_ALLOWED_HOSTS"]


def test_nginx_turn_location_streams_before_completion_and_limits_bursts(tmp_path):
    nginx = shutil.which("nginx")
    if not nginx or os.geteuid() == 0:
        pytest.skip("An unprivileged local nginx is required; no Docker or system service is used")
    finish = threading.Event()

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            if body == b"stream":
                finish.wait(2)
            self.wfile.write(b"data: done\n\n")

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Upstream) as upstream:
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        zone = (ROOT / "local-dev/nginx-assistant-http.conf").read_text()
        route = location_block((ROOT / "local-dev/nginx-public-pages.conf").read_text(), "location = /api/v1/assistant/turn")
        route = route.replace("http://127.0.0.1:8018", f"http://127.0.0.1:{upstream.server_port}")
        config = tmp_path / "nginx.conf"
        config.write_text(f"""worker_processes 1;
pid {tmp_path}/nginx.pid;
lock_file {tmp_path}/nginx.lock;
error_log {tmp_path}/error.log;
events {{ worker_connections 512; }}
http {{
 access_log off;
 client_body_temp_path {tmp_path}/body;
 proxy_temp_path {tmp_path}/proxy;
 fastcgi_temp_path {tmp_path}/fastcgi;
 uwsgi_temp_path {tmp_path}/uwsgi;
 scgi_temp_path {tmp_path}/scgi;
 {zone}
 server {{ listen 127.0.0.1:{port}; location = /health {{ return 200; }} {route} }}
}}""")
        command = [nginx, "-p", str(tmp_path) + "/", "-c", str(config), "-e", str(tmp_path / "error.log")]
        checked = subprocess.run([*command, "-t"], capture_output=True)
        assert checked.returncode == 0, checked.stderr.decode()
        process = subprocess.Popen([*command, "-g", "daemon off; master_process off;"])
        try:
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(timeout=4) as client:
                for _ in range(50):
                    try:
                        if client.get(base + "/health").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(.05)
                began = time.monotonic()
                with client.stream("POST", base + "/api/v1/assistant/turn", content=b"stream") as response:
                    assert response.status_code == 200
                    assert next(response.iter_lines()) == "data: first"
                    assert time.monotonic() - began < 1.5  # Must arrive before upstream completes.
                    finish.set()
                statuses = [client.post(base + "/api/v1/assistant/turn").status_code for _ in range(100)]
                assert 200 in statuses and 429 in statuses
        finally:
            finish.set()
            process.terminate()
            process.wait(timeout=5)
            upstream.shutdown()

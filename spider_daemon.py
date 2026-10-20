"""
Spider Dashboard Daemon — persistent monitoring server.

Started at Windows login by the dashboard keep-alive chain (Startup folder
-> meta_watchdog_spider.vbs -> meta_watchdog_spider.ps1 -> watchdog_spider.ps1,
which spawns this as `python spider_daemon.py`). Runs the dashboard HTTP server
on the main thread so it stays alive until the user logs out or shuts down.

This is a monitoring dashboard only — it never triggers the pipeline. Daily
scheduling is hosted by WorkBuddy (see README「调度」).

Usage:
    pythonw.exe spider_daemon.py          # background (via the watchdog chain)
    python spider_daemon.py --foreground   # foreground with console output
"""

import http.server
import socket
import socketserver
import sys
import time
import urllib.request
import webbrowser
from datetime import datetime
from functools import partial
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PORT = 8765
DASHBOARD_URL = f"http://localhost:{PORT}/dashboard.html"


def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


def wait_for_network(timeout=120):
    """Block until we can reach the internet, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen("https://www.baidu.com", timeout=5)
            return True
        except Exception:
            time.sleep(2)
    return False


def main():
    foreground = "--foreground" in sys.argv

    if not foreground:
        # Redirect stdout/stderr to a log file for silent operation
        log_dir = BASE_DIR / "logs" / "daemon"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"daemon_{datetime.now().strftime('%Y-%m-%d')}.log"
        sys.stdout = open(log_path, "a", encoding="utf-8")
        sys.stderr = sys.stdout

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Spider Daemon starting...")

    if _port_in_use(PORT):
        print(f"  Port {PORT} already in use — another daemon is running, exiting")
        sys.exit(0)

    # Start HTTP server FIRST so local dashboard is available immediately
    import json
    _HEALTH_OK = json.dumps({"ok": True, "api_configured": True}).encode()

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(BASE_DIR), **kwargs)
        def do_GET(self):
            if self.path == '/health':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(_HEALTH_OK)
                return
            if self.path == '/dashboard/status.html':
                self.path = '/dashboard.html'
                super().do_GET()
                return
            super().do_GET()
        def log_message(self, format, *args):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(("", PORT), _Handler)
    except OSError as e:
        print(f"  Cannot bind port {PORT}: {e}")
        sys.exit(1)

    print(f"  Dashboard: {DASHBOARD_URL}")

    # Start serving immediately — network check is non-critical for local dashboard
    import threading
    _server_ready = threading.Event()

    def _serve():
        _server_ready.set()
        httpd.serve_forever()

    _t = threading.Thread(target=_serve, daemon=True)
    _t.start()
    _server_ready.wait()

    # Network check (background, doesn't block dashboard)
    if not wait_for_network(timeout=5):
        print("  No network — running in offline mode")

    try:
        webbrowser.open(DASHBOARD_URL)
    except Exception:
        pass

    print("  Daemon running — press Ctrl+C to stop")
    try:
        while _t.is_alive():
            _t.join(1)
    except KeyboardInterrupt:
        print("  Shutting down...")
        httpd.shutdown()


if __name__ == "__main__":
    main()

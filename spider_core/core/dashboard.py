"""
Shared dashboard HTTP server + browser auto-open.
Used by generate_report.py, fetch_ai_news.py, and cognition/curator.py
so the monitoring HTML is available regardless of which entry point is invoked.
"""
import http.server
import socket
import socketserver
import threading
import time
import urllib.request
import webbrowser
from functools import partial


def _port_in_use(port):
    """Check if a port has a live listener (cross-platform).

    Uses connect() rather than bind() — connect succeeds only if someone
    is actively listening. Bind-based checks fail on Windows where
    SO_REUSEADDR allows co-binding, and on TIME_WAIT (rebind denied
    even though nothing is listening).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


def start_http_server(base_dir, port=8765):
    """Start a tiny HTTP server in a daemon thread.

    Returns the server instance, or None if port is already in use.
    Pre-checks port availability so subprocesses don't accidentally
    rebind on Windows where SO_REUSEADDR allows multiple binds.
    """
    if _port_in_use(port):
        print(f"  [Dashboard] Port {port} already in use — reusing existing server")
        return None

    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(base_dir))
    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(("", port), handler)
    except OSError:
        print(f"  [Dashboard] Port {port} already in use — reusing existing server")
        return None
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def open_dashboard(url="http://localhost:8765/dashboard.html", port=8765):
    """Try to open dashboard in browser.

    Polls the server until it's ready (up to 3s), then attempts
    webbrowser.open(). Graceful no-op on headless/non-interactive sessions.
    """
    print(f"\n  [Dashboard] {url}")

    # Wait for server to be ready before opening browser
    status_url = f"http://localhost:{port}/pipeline_status.json"
    for _ in range(15):
        try:
            urllib.request.urlopen(status_url, timeout=0.3)
            break
        except Exception:
            time.sleep(0.2)

    try:
        webbrowser.open(url)
    except Exception:
        pass

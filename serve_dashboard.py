import http.server
import socketserver
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress access logs

s = socketserver.TCPServer(("127.0.0.1", 8765), QuietHandler)
print("Dashboard: http://localhost:8765/dashboard.html")
s.serve_forever()

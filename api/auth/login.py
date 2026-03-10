"""
GET /api/auth/login?user_id=<uid>
Redirects the user to Google's OAuth2 consent screen.
Vercel Python runtime — must use BaseHTTPRequestHandler pattern.
"""
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed  = urlparse(self.path)
        params  = parse_qs(parsed.query)
        user_id = (params.get("user_id") or [""])[0]

        if not user_id:
            self._json(400, b'{"error":"Missing user_id parameter"}')
            return

        try:
            qs = urlencode({
                "client_id":     os.environ["GOOGLE_CLIENT_ID"],
                "redirect_uri":  os.environ["GOOGLE_REDIRECT_URI"],
                "response_type": "code",
                "scope":         "https://www.googleapis.com/auth/gmail.readonly",
                "access_type":   "offline",
                "prompt":        "consent",
                "state":         user_id,
            })
            self.send_response(302)
            self.send_header("Location", f"https://accounts.google.com/o/oauth2/v2/auth?{qs}")
            self.end_headers()

        except Exception as e:
            self._json(500, f'{{"error":"{e}"}}'.encode())

    def _json(self, status, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

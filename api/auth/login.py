"""
GET /api/auth/login
Redirects the user to Google's OAuth2 consent screen.
"""
import os
from urllib.parse import urlencode
from api._utils import redirect_response, error_response


def handler(request, response):
    try:
        client_id = os.environ["GOOGLE_CLIENT_ID"]
        redirect_uri = os.environ["GOOGLE_REDIRECT_URI"]

        # state carries the Supabase user_id so we can link tokens after callback
        user_id = request.args.get("user_id", "")
        if not user_id:
            return error_response("Missing user_id parameter", 400)

        params = urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
            "access_type": "offline",
            "prompt": "consent",          # force refresh_token every time
            "state": user_id,
        })

        google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
        return redirect_response(google_auth_url)

    except Exception as e:
        return error_response(f"Login error: {str(e)}", 500)

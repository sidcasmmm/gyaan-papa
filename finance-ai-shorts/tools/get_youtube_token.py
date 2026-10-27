"""Run this ONCE on your own computer to connect your YouTube channel.

    pip install google-auth-oauthlib
    python tools/get_youtube_token.py client_secret.json

A browser window opens → sign in with the Google account that owns the channel →
allow access. The script prints three values to paste into GitHub Secrets.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

if len(sys.argv) < 2:
    sys.exit("Usage: python tools/get_youtube_token.py path/to/client_secret.json")

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
info = json.load(open(sys.argv[1]))
client = info.get("installed") or info.get("web")

print("\n✅ Connected! Add these as GitHub repository secrets:\n")
print(f"YT_CLIENT_ID      = {client['client_id']}")
print(f"YT_CLIENT_SECRET  = {client['client_secret']}")
print(f"YT_REFRESH_TOKEN  = {creds.refresh_token}")
print("\nKeep these private — anyone with them can upload to your channel.")

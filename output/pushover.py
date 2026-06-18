"""
PEACHY ENGINE — Pushover output
=============================================================================
Sends the briefing to your phone. Same Pushover account you used for FLOWSENSE.
One notification per ticker, titled so you can read it from the lock screen.
=============================================================================
"""

import urllib.request
import urllib.parse

from config import settings


def send(title: str, message: str) -> bool:
    """Send a single Pushover notification. Returns True on success."""
    if not settings.SEND_PUSHOVER:
        return False

    data = urllib.parse.urlencode({
        "token": settings.PUSHOVER_APP_TOKEN,
        "user": settings.PUSHOVER_USER_KEY,
        "title": title,
        "message": message,
    }).encode()

    try:
        req = urllib.request.Request(
            "https://api.pushover.net/1/messages.json", data=data
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:  # noqa: BLE001
        print(f"[pushover] failed: {e}")
        return False

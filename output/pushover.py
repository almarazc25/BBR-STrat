"""
PEACHY ENGINE — Pushover output
=============================================================================
Sends the briefing to your phone.

What this hardened version does that the old one didn't:
    * Retries up to PUSHOVER_RETRY_ATTEMPTS times with exponential backoff
      (catches transient network blips that would silently drop a message).
    * Parses and logs Pushover's response body when it isn't 200 OK, so we
      actually know WHY a send was rejected if it ever is.
    * Sends a real User-Agent and Content-Type header (some firewall/CDN
      paths treat header-less requests differently).
    * Optional `PUSHOVER_DEVICE` targeting — when set, the message goes to
      ONLY that device. Bypasses any stale device on the account that
      might be intercepting / mis-decrypting messages.
    * Strips characters Pushover/iOS sometimes choke on if PUSHOVER_SAFE_ASCII
      is true (defaults to false; only turn on if you're chasing a bug).
=============================================================================
"""

import time
import json
import urllib.request
import urllib.parse
import urllib.error

from config import settings

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
USER_AGENT = "PeachyEngine/1.0 (+https://github.com/almarazc25/bbr-strat)"


def _safe_ascii(s: str) -> str:
    """Strip non-ASCII characters (e.g. the ★ star, em-dashes, fancy quotes).
    Used only when PUSHOVER_SAFE_ASCII is enabled — a debug aid in case a
    Unicode glyph is what's confusing the iOS client."""
    if not s:
        return s
    return s.encode("ascii", "ignore").decode("ascii")


def send(title: str, message: str) -> bool:
    """Send a single Pushover notification. Returns True on success."""
    if not settings.SEND_PUSHOVER:
        return False

    if getattr(settings, "PUSHOVER_SAFE_ASCII", False):
        title = _safe_ascii(title)
        message = _safe_ascii(message)

    payload = {
        "token": settings.PUSHOVER_APP_TOKEN,
        "user": settings.PUSHOVER_USER_KEY,
        "title": title,
        "message": message,
    }
    # Targeting a specific device bypasses ALL other devices on the account.
    # If a stale phone/tablet/old install is intercepting messages, this
    # cleanly side-steps that without the user having to clean up their
    # account.
    device = getattr(settings, "PUSHOVER_DEVICE", "") or ""
    if device:
        payload["device"] = device

    data = urllib.parse.urlencode(payload).encode("utf-8")

    attempts = max(1, getattr(settings, "PUSHOVER_RETRY_ATTEMPTS", 3))
    last_err = None

    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                PUSHOVER_URL,
                data=data,
                headers={
                    "User-Agent": USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if resp.status == 200:
                    return True
                # 200-but-no? Or any other 2xx? Log + retry.
                last_err = f"HTTP {resp.status}: {body}"
                print(f"[pushover] non-200 (attempt {attempt+1}/{attempts}): "
                      f"{last_err}")
        except urllib.error.HTTPError as e:
            # 4xx/5xx — read body for Pushover's error message
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            last_err = f"HTTPError {e.code}: {body}"
            print(f"[pushover] {last_err} (attempt {attempt+1}/{attempts})")
            # 4xx (bad token / user / device) won't be fixed by retrying.
            if 400 <= e.code < 500:
                return False
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            print(f"[pushover] send failed (attempt {attempt+1}/{attempts}): "
                  f"{last_err}")

        if attempt < attempts - 1:
            wait = 1.5 * (2 ** attempt)  # 1.5s, 3s, 6s
            time.sleep(wait)

    print(f"[pushover] gave up after {attempts} attempts. Last error: "
          f"{last_err}")
    return False

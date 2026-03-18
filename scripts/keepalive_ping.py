import os
import urllib.request
import urllib.error
from datetime import datetime, timezone


def main():
    url = os.getenv("RENDER_HEALTH_URL", "https://aayu-ayurvedic-ai-1.onrender.com/health")
    timeout = int(os.getenv("PING_TIMEOUT_SECONDS", "20"))

    req = urllib.request.Request(url, headers={"User-Agent": "aayu-keepalive/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.getcode()
            ts = datetime.now(timezone.utc).isoformat()
            print(f"[{ts}] keepalive ok: {status} {url}")
    except urllib.error.HTTPError as exc:
        ts = datetime.now(timezone.utc).isoformat()
        print(f"[{ts}] keepalive http error: {exc.code} {url}")
        raise
    except Exception as exc:
        ts = datetime.now(timezone.utc).isoformat()
        print(f"[{ts}] keepalive failed: {exc}")
        raise


if __name__ == "__main__":
    main()

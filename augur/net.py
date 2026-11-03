"""Small HTTP helpers (standard library only, so there is nothing to install)."""
import json
import ssl
import time
import urllib.error
import urllib.request

USER_AGENT = "Augur/1.0 (ARAM Mayhem stats; github.com)"


class HTTPError(Exception):
    def __init__(self, status, url, body="", headers=None):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.body = body
        self.headers = headers or {}


def request(url, headers=None, timeout=30, insecure=False):
    """Return (status, headers, body_bytes). Raises HTTPError on 4xx/5xx."""
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    ctx = None
    if insecure:  # the League client and game use self-signed certificates on 127.0.0.1
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        raise HTTPError(e.code, url, e.read().decode("utf-8", "replace"), dict(e.headers)) from None


def get_json(url, headers=None, timeout=30, retries=3, insecure=False):
    last = None
    for attempt in range(retries):
        try:
            return json.loads(request(url, headers, timeout, insecure)[2])
        except HTTPError as e:
            if e.status < 500:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise last


def get_text(url, headers=None, timeout=30, retries=3):
    last = None
    for attempt in range(retries):
        try:
            return request(url, headers, timeout)[2].decode("utf-8")
        except HTTPError as e:
            if e.status < 500:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise last

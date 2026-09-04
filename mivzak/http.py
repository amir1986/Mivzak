"""Small HTTP helpers with retries, used by every network-facing module."""

from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}


class HttpError(RuntimeError):
    def __init__(self, url: str, status: int | None, message: str):
        super().__init__(f"{message} ({url})")
        self.url = url
        self.status = status


class Session:
    """A cookie-keeping urllib session with polite retries.

    ``delays`` lists the sleep before each retry; a 429 waits at least
    ``rate_limit_delay`` seconds because Yahoo throttles bursts hard.
    """

    def __init__(self, delays=(3, 8), rate_limit_delay: float = 15.0):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.delays = tuple(delays)
        self.rate_limit_delay = rate_limit_delay

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict | None = None,
        timeout: float = 30,
        attempts: int | None = None,
    ) -> tuple[int, bytes, dict]:
        base_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
        }
        if headers:
            base_headers.update(headers)
        attempts = attempts or (len(self.delays) + 1)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(
                url, data=data, headers=base_headers, method=method
            )
            try:
                with self.opener.open(request, timeout=timeout) as response:
                    return response.status, response.read(), dict(response.headers)
            except urllib.error.HTTPError as error:
                body = error.read()[:500].decode("utf-8", "replace")
                last_error = HttpError(url, error.code, f"HTTP {error.code}: {body[:200]}")
                if error.code not in RETRY_STATUSES or attempt == attempts:
                    raise last_error from error
                delay = self.delays[min(attempt - 1, len(self.delays) - 1)]
                if error.code == 429:
                    delay = max(delay, self.rate_limit_delay * attempt)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_error = HttpError(url, None, f"network error: {error}")
                if attempt == attempts:
                    raise last_error from error
                delay = self.delays[min(attempt - 1, len(self.delays) - 1)]
            print(f"Retrying {url.split('?')[0]} in {delay:.0f}s (attempt {attempt + 1}/{attempts})")
            time.sleep(delay)

        raise last_error or HttpError(url, None, "unknown error")

    def get_text(self, url: str, **kwargs) -> str:
        _, body, _ = self.request(url, **kwargs)
        return body.decode("utf-8", "replace")

    def get_json(self, url: str, **kwargs):
        headers = {"Accept": "application/json,text/plain,*/*"}
        headers.update(kwargs.pop("headers", None) or {})
        _, body, _ = self.request(url, headers=headers, **kwargs)
        return json.loads(body.decode("utf-8", "replace"))

    def post_json(self, url: str, payload: dict, headers: dict | None = None, **kwargs):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        base = {"Content-Type": "application/json", "Accept": "application/json"}
        base.update(headers or {})
        _, body, _ = self.request(url, method="POST", data=data, headers=base, **kwargs)
        return json.loads(body.decode("utf-8", "replace"))


DEFAULT_SESSION = Session()


def get_text(url: str, **kwargs) -> str:
    return DEFAULT_SESSION.get_text(url, **kwargs)


def get_json(url: str, **kwargs):
    return DEFAULT_SESSION.get_json(url, **kwargs)


def post_json(url: str, payload: dict, headers: dict | None = None, **kwargs):
    return DEFAULT_SESSION.post_json(url, payload, headers=headers, **kwargs)


def browser_get(url: str, timeout: float = 30) -> tuple[int, str] | None:
    """Fetch with a browser TLS fingerprint when curl_cffi is installed.

    Yahoo throttles plain Python clients on shared cloud addresses far more
    than browsers, so this is tried first for Yahoo and silently skipped when
    the optional dependency is missing or fails.
    """
    try:
        from curl_cffi import requests as browser_requests  # type: ignore
    except Exception:
        return None
    try:
        response = browser_requests.get(
            url,
            impersonate="chrome",
            timeout=timeout,
            headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        return response.status_code, response.text
    except Exception as error:
        print(f"Browser-style fetch failed for {url.split('?')[0]}: {error}")
        return None


def encode_query(params: dict) -> str:
    return urllib.parse.urlencode(params, quote_via=urllib.parse.quote)

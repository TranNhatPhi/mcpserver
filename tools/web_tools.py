"""Web access tools backed by httpx."""

import httpx

MAX_RESPONSE_CHARS = 20_000
DEFAULT_TIMEOUT = 30.0

# Single shared client — persistent TCP connection pool across all requests.
# Avoids the per-request TLS handshake overhead that dominates latency under load.
_shared_client = httpx.AsyncClient(
    follow_redirects=True,
    timeout=DEFAULT_TIMEOUT,
    limits=httpx.Limits(
        max_connections=200,
        max_keepalive_connections=40,
        keepalive_expiry=30,
    ),
)


async def fetch_url(url: str) -> str:
    """Fetch a URL via HTTP GET and return the status code and (truncated) body."""
    response = await _shared_client.get(url)
    return _format_response(response)


async def http_request(
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    body: str | None = None,
) -> str:
    """Make a general HTTP request (GET/POST/PUT/DELETE/...) and return status + body.

    `headers` is an optional dict of request headers; `body` is an optional
    raw string request body (e.g. JSON-encoded text).
    """
    response = await _shared_client.request(
        method.upper(), url, headers=headers, content=body
    )
    return _format_response(response)


def _format_response(response: httpx.Response) -> str:
    text = response.text
    truncated = ""
    if len(text) > MAX_RESPONSE_CHARS:
        text = text[:MAX_RESPONSE_CHARS]
        truncated = f"\n...[truncated to {MAX_RESPONSE_CHARS} characters]"
    return (
        f"HTTP {response.status_code} {response.reason_phrase}\n"
        f"URL: {response.url}\n"
        f"Content-Type: {response.headers.get('content-type', '?')}\n\n"
        f"{text}{truncated}"
    )

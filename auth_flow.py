import json
import time
import uuid
import os
import asyncio
from typing import Dict, Tuple, Optional

import httpx

def _get_proxies() -> Optional[Dict[str, str]]:
    proxy = os.getenv("HTTP_PROXY", "").strip()
    if proxy:
        return {"http": proxy, "https": proxy}
    return None

# OIDC endpoints and constants (aligned with v1/auth_client.py)
OIDC_BASE = "https://oidc.us-east-1.amazonaws.com"
REGISTER_URL = f"{OIDC_BASE}/client/register"
DEVICE_AUTH_URL = f"{OIDC_BASE}/device_authorization"
TOKEN_URL = f"{OIDC_BASE}/token"
DEFAULT_START_URL = "https://view.awsapps.com/start"

USER_AGENT = "aws-sdk-rust/1.3.9 os/windows lang/rust/1.87.0"
X_AMZ_USER_AGENT = "aws-sdk-rust/1.3.9 ua/2.1 api/ssooidc/1.88.0 os/windows lang/rust/1.87.0 m/E app/AmazonQ-For-CLI"
AMZ_SDK_REQUEST = "attempt=1; max=3"


def make_headers() -> Dict[str, str]:
    return {
        "content-type": "application/json",
        "user-agent": USER_AGENT,
        "x-amz-user-agent": X_AMZ_USER_AGENT,
        "amz-sdk-request": AMZ_SDK_REQUEST,
        "amz-sdk-invocation-id": str(uuid.uuid4()),
    }


async def post_json(client: httpx.AsyncClient, url: str, payload: Dict) -> httpx.Response:
    # Keep JSON order and mimic body closely to v1
    payload_str = json.dumps(payload, ensure_ascii=False)
    headers = make_headers()
    resp = await client.post(url, headers=headers, content=payload_str, timeout=httpx.Timeout(15.0, read=60.0))
    return resp


async def register_client_min() -> Tuple[str, str]:
    """
    Register an OIDC client (minimal) and return (clientId, clientSecret).
    """
    payload = {
        "clientName": "Amazon Q Developer for command line",
        "clientType": "public",
        "scopes": [
            "codewhisperer:completions",
            "codewhisperer:analysis",
            "codewhisperer:conversations",
        ],
    }
    proxies = _get_proxies()
    mounts = None
    if proxies:
        proxy_url = proxies.get("https") or proxies.get("http")
        if proxy_url:
            mounts = {
                "https://": httpx.AsyncHTTPTransport(proxy=proxy_url),
                "http://": httpx.AsyncHTTPTransport(proxy=proxy_url),
            }
    async with httpx.AsyncClient(mounts=mounts) as client:
        r = await post_json(client, REGISTER_URL, payload)
        r.raise_for_status()
        data = r.json()
        return data["clientId"], data["clientSecret"]


async def device_authorize(client_id: str, client_secret: str, start_url: Optional[str] = None) -> Dict:
    """
    Start device authorization. Returns dict that includes:
    - deviceCode
    - interval
    - expiresIn
    - verificationUriComplete
    - userCode
    """
    payload = {
        "clientId": client_id,
        "clientSecret": client_secret,
        "startUrl": start_url or DEFAULT_START_URL,
    }
    proxies = _get_proxies()
    mounts = None
    if proxies:
        proxy_url = proxies.get("https") or proxies.get("http")
        if proxy_url:
            mounts = {
                "https://": httpx.AsyncHTTPTransport(proxy=proxy_url),
                "http://": httpx.AsyncHTTPTransport(proxy=proxy_url),
            }
    async with httpx.AsyncClient(mounts=mounts) as client:
        r = await post_json(client, DEVICE_AUTH_URL, payload)
        r.raise_for_status()
        return r.json()


async def poll_token_device_code(
    client_id: str,
    client_secret: str,
    device_code: str,
    interval: int,
    expires_in: int,
    max_timeout_sec: Optional[int] = 300,
) -> Dict:
    """
    Poll token with device_code until approved or timeout.
    - Respects upstream expires_in, but caps total time by max_timeout_sec (default 5 minutes).
    Returns token dict with at least 'accessToken' and optionally 'refreshToken'.
    Raises:
      - TimeoutError on timeout
      - httpx.HTTPError for non-recoverable HTTP errors
    """
    payload = {
        "clientId": client_id,
        "clientSecret": client_secret,
        "deviceCode": device_code,
        "grantType": "urn:ietf:params:oauth:grant-type:device_code",
    }

    now = time.time()
    upstream_deadline = now + max(1, int(expires_in))
    cap_deadline = now + max_timeout_sec if (max_timeout_sec and max_timeout_sec > 0) else upstream_deadline
    deadline = min(upstream_deadline, cap_deadline)

    # Ensure interval sane
    poll_interval = max(1, int(interval or 1))

    proxies = _get_proxies()
    mounts = None
    if proxies:
        proxy_url = proxies.get("https") or proxies.get("http")
        if proxy_url:
            mounts = {
                "https://": httpx.AsyncHTTPTransport(proxy=proxy_url),
                "http://": httpx.AsyncHTTPTransport(proxy=proxy_url),
            }
    
    async with httpx.AsyncClient(mounts=mounts) as client:
        while time.time() < deadline:
            r = await post_json(client, TOKEN_URL, payload)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 400:
                # Expect AuthorizationPendingException early on
                try:
                    err = r.json()
                except Exception:
                    err = {"error": r.text}
                if str(err.get("error")) == "authorization_pending":
                    await asyncio.sleep(poll_interval)
                    continue
                # Other 4xx are errors
                r.raise_for_status()
            # Non-200, non-400
            r.raise_for_status()

    raise TimeoutError("Device authorization expired before approval (timeout reached)")
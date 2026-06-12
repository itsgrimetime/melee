"""Shared helpers for sync commands."""

import asyncio
import json
import random
from dataclasses import dataclass
from pathlib import Path

from src.client import DecompMeAPIError, DecompMeAuthError

from .._common import (
    PRODUCTION_COOKIES_FILE,
    console,
)

# Rate limiting configuration for production API
RATE_LIMIT_DELAY = 1.0  # Base delay between requests (seconds)
RATE_LIMIT_MAX_RETRIES = 5  # Max retries on 429
RATE_LIMIT_BACKOFF_FACTOR = 2.0  # Exponential backoff multiplier


async def rate_limited_request(client, method: str, url: str, max_retries: int = RATE_LIMIT_MAX_RETRIES, **kwargs):
    """Make a rate-limited request with 429 handling and exponential backoff.

    Args:
        client: httpx.AsyncClient instance
        method: HTTP method (get, post, etc.)
        url: URL to request
        max_retries: Maximum number of retries on 429
        **kwargs: Additional arguments to pass to the request

    Returns:
        httpx.Response object

    Raises:
        Exception if max retries exceeded
    """
    delay = RATE_LIMIT_DELAY

    for attempt in range(max_retries + 1):
        request_method = getattr(client, method.lower())
        response = await request_method(url, **kwargs)

        if response.status_code == 429:
            # Rate limited - check for Retry-After header
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    wait_time = float(retry_after)
                except ValueError:
                    wait_time = delay * RATE_LIMIT_BACKOFF_FACTOR
            else:
                wait_time = delay * RATE_LIMIT_BACKOFF_FACTOR

            if attempt < max_retries:
                console.print(
                    f"[yellow]Rate limited (429). Waiting {wait_time:.1f}s before retry {attempt + 1}/{max_retries}...[/yellow]"
                )
                await asyncio.sleep(wait_time)
                delay = wait_time * RATE_LIMIT_BACKOFF_FACTOR  # Increase delay for next attempt
                continue
            else:
                raise Exception(f"Rate limit exceeded after {max_retries} retries")

        # Add delay after successful request to be polite to the server
        jitter = random.uniform(0, delay * 0.1)
        await asyncio.sleep(delay + jitter)

        return response

    raise Exception("Unexpected: loop completed without returning")


def load_production_cookies() -> dict[str, str]:
    """Load production cookies from cache file."""
    if not PRODUCTION_COOKIES_FILE.exists():
        return {}
    try:
        with open(PRODUCTION_COOKIES_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_production_cookies(cookies: dict[str, str]) -> None:
    """Save production cookies to cache file."""
    PRODUCTION_COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PRODUCTION_COOKIES_FILE, "w") as f:
        json.dump(cookies, f, indent=2)


@dataclass
class ProductionCreateResult:
    """Outcome of creating + claiming a production scratch."""

    slug: str
    claim_token: str | None
    claimed: bool


async def claim_production_scratch(prod_client, slug: str, token: str) -> bool:
    """Claim ownership of a production scratch. Returns True iff ownership took.

    Claim failure is non-fatal (the scratch still exists, claimable later), so
    this returns False rather than raising.
    """
    resp = await rate_limited_request(
        prod_client, "post", f"/api/scratch/{slug}/claim", json={"token": token}
    )
    if resp.status_code == 200:
        try:
            return bool(resp.json().get("success"))
        except Exception:
            return False
    return False


async def create_and_claim_production_scratch(prod_client, create_data: dict) -> ProductionCreateResult:
    """POST a scratch to production and claim it.

    Raises ``DecompMeAuthError`` on 403 (Cloudflare / expired cf_clearance) so a
    batch caller can stop; raises ``DecompMeAPIError`` on other non-2xx. Claim
    failures are reported via ``ProductionCreateResult.claimed`` (not raised).
    """
    resp = await rate_limited_request(prod_client, "post", "/api/scratch", json=create_data)
    if resp.status_code == 403:
        raise DecompMeAuthError(f"Production create blocked (403): {resp.text[:200]}")
    if resp.status_code not in (200, 201):
        raise DecompMeAPIError(f"Production create failed: {resp.status_code} - {resp.text[:200]}")

    data = resp.json()
    slug = data.get("slug")
    token = data.get("claim_token")
    claimed = False
    if token:
        claimed = await claim_production_scratch(prod_client, slug, token)
    return ProductionCreateResult(slug=slug, claim_token=token, claimed=claimed)

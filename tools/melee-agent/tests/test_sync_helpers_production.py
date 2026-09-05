"""Tests for the shared production create+claim helper (respx-mocked httpx)."""

import httpx
import pytest
import respx

from src.client import DecompMeAPIError, DecompMeAuthError
from src.cli.sync._helpers import (
    ProductionCreateResult,
    claim_production_scratch,
    create_and_claim_production_scratch,
)

PAYLOAD = {"name": "fn_1", "target_asm": "x", "context": "", "compiler": "mwcc_233_163n"}


@pytest.fixture(autouse=True)
def _no_rate_limit_sleep(monkeypatch):
    # rate_limited_request sleeps ~1s after each request; zero it for tests.
    monkeypatch.setattr("src.cli.sync._helpers.RATE_LIMIT_DELAY", 0.0)


@respx.mock
async def test_create_and_claim_happy():
    respx.post("https://decomp.me/api/scratch").mock(
        return_value=httpx.Response(201, json={"slug": "abc123", "claim_token": "tok"})
    )
    respx.post("https://decomp.me/api/scratch/abc123/claim").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        result = await create_and_claim_production_scratch(client, PAYLOAD)
    assert isinstance(result, ProductionCreateResult)
    assert result.slug == "abc123"
    assert result.claim_token == "tok"
    assert result.claimed is True


@respx.mock
async def test_create_403_raises_auth_error():
    respx.post("https://decomp.me/api/scratch").mock(return_value=httpx.Response(403, text="blocked"))
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        with pytest.raises(DecompMeAuthError):
            await create_and_claim_production_scratch(client, PAYLOAD)


@respx.mock
async def test_create_500_raises_api_error():
    respx.post("https://decomp.me/api/scratch").mock(return_value=httpx.Response(500, text="boom"))
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        with pytest.raises(DecompMeAPIError):
            await create_and_claim_production_scratch(client, PAYLOAD)


@respx.mock
async def test_claim_failure_returns_not_claimed():
    respx.post("https://decomp.me/api/scratch").mock(
        return_value=httpx.Response(201, json={"slug": "abc123", "claim_token": "tok"})
    )
    respx.post("https://decomp.me/api/scratch/abc123/claim").mock(
        return_value=httpx.Response(200, json={"success": False})
    )
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        result = await create_and_claim_production_scratch(client, PAYLOAD)
    assert result.slug == "abc123"
    assert result.claimed is False


@respx.mock
async def test_no_claim_token_means_not_claimed():
    respx.post("https://decomp.me/api/scratch").mock(
        return_value=httpx.Response(201, json={"slug": "abc123", "claim_token": None})
    )
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        result = await create_and_claim_production_scratch(client, PAYLOAD)
    assert result.claimed is False


@respx.mock
async def test_429_then_201_succeeds_via_backoff():
    respx.post("https://decomp.me/api/scratch").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(201, json={"slug": "abc123", "claim_token": None}),
        ]
    )
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        result = await create_and_claim_production_scratch(client, PAYLOAD)
    assert result.slug == "abc123"


@respx.mock
async def test_claim_production_scratch_helper():
    respx.post("https://decomp.me/api/scratch/s1/claim").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    async with httpx.AsyncClient(base_url="https://decomp.me") as client:
        assert await claim_production_scratch(client, "s1", "tok") is True

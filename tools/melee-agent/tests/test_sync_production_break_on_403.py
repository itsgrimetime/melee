"""Regression: a create-path 403 must STOP the batch (not keep hammering
production with a known-bad cf_clearance). Locks the behavior across the
helper-extraction refactor."""

from src.client import DecompMeAuthError


class _FakeLocalScratch:
    name = "fn_1"
    compiler = "mwcc_233_163n"
    platform = "gc_wii"
    compiler_flags = "-O4,p"
    diff_flags: list = []
    # Long, non-placeholder body so the prod sync uses it directly (no repo refresh).
    source_code = "void fn_1(void) { int x = 0; (void)x; /* real-looking body padding */ }"
    context = ""
    diff_label = "fn_1"


class _FakeLocalClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get_scratch(self, slug):
        return _FakeLocalScratch()

    async def export_scratch(self, slug, target_only=False):
        raise RuntimeError("no export in test")  # caught -> target_asm=""


class _FakeResp:
    status_code = 200

    def json(self):
        return {"results": []}


async def _fake_rate_limited_request(client, method, url, **kwargs):
    return _FakeResp()


def test_403_stops_the_batch(tmp_path, monkeypatch):
    from src.db import StateDB, reset_db
    import src.cli.sync.production as prod

    reset_db()
    db = StateDB(tmp_path / "t.db")
    db.upsert_function("fn_1", local_scratch_slug="l1", match_percent=50.0)
    db.upsert_function("fn_2", local_scratch_slug="l2", match_percent=40.0)

    calls = {"create": 0}

    async def _fake_create_and_claim(prod_client, create_data):
        calls["create"] += 1
        raise DecompMeAuthError("403")

    # Keep the test hermetic: synced_scratches.json is written next to this path.
    monkeypatch.setattr(prod, "PRODUCTION_COOKIES_FILE", tmp_path / "production_cookies.json")
    monkeypatch.setattr("src.db.get_db", lambda *a, **k: db)
    monkeypatch.setattr(prod, "load_production_cookies", lambda: {"cf_clearance": "x", "sessionid": "y"})
    monkeypatch.setattr(prod, "rate_limited_request", _fake_rate_limited_request)
    monkeypatch.setattr(prod, "create_and_claim_production_scratch", _fake_create_and_claim)
    monkeypatch.setattr("src.client.DecompMeAPIClient", _FakeLocalClient)

    prod.production_command(
        melee_root=tmp_path,
        local_url="http://localhost:8000",
        min_match=0.0,
        limit=10,
        dry_run=False,
        force=False,
        function=None,
        slug=None,
    )

    # Two functions queued, but the first 403 must break the loop.
    assert calls["create"] == 1

    db.close()
    reset_db()

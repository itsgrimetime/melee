"""Tests for `melee-agent sync auth` cookie handling."""


def test_session_id_flag_updates_only_sessionid(monkeypatch):
    """Passing --session-id with an existing cf_clearance must update the
    sessionid WITHOUT re-prompting for cf_clearance (regression: refreshing a
    stale/anon sessionid was impossible because the prompt only fired when no
    sessionid existed)."""
    import src.cli.sync.auth as auth

    saved = {}
    monkeypatch.setattr(
        auth,
        "load_production_cookies",
        lambda: {"cf_clearance": "cf", "user_agent": "ua", "sessionid": "old-anon"},
    )
    monkeypatch.setattr(auth, "save_production_cookies", lambda c: saved.update(c))
    monkeypatch.setattr(auth, "status_command", lambda: None)

    def _no_prompt():
        raise AssertionError("_prompt_cf_clearance must not run when refreshing sessionid only")

    monkeypatch.setattr(auth, "_prompt_cf_clearance", _no_prompt)

    auth.auth_command(cf_clearance=None, user_agent=None, session_id="fresh-logged-in")

    assert saved["sessionid"] == "fresh-logged-in"
    assert saved["cf_clearance"] == "cf"
    assert saved["user_agent"] == "ua"


def test_interactive_offers_to_replace_existing_sessionid(monkeypatch):
    """Interactive mode (no --session-id) must OFFER to replace an existing
    sessionid, not silently skip it."""
    import src.cli.sync.auth as auth

    saved = {}
    monkeypatch.setattr(
        auth,
        "load_production_cookies",
        lambda: {"cf_clearance": "cf", "user_agent": "ua", "sessionid": "old-anon"},
    )
    monkeypatch.setattr(auth, "save_production_cookies", lambda c: saved.update(c))
    monkeypatch.setattr(auth, "status_command", lambda: None)
    monkeypatch.setattr(auth, "_prompt_cf_clearance", lambda: ("cf2", "ua2"))

    asked = {}

    def _fake_confirm(question, default=False):
        asked["question"] = question
        return True  # user agrees to replace

    monkeypatch.setattr(auth.typer, "confirm", _fake_confirm)
    monkeypatch.setattr(auth.typer, "prompt", lambda *a, **k: "replacement-sid")

    auth.auth_command(cf_clearance=None, user_agent=None, session_id=None)

    assert "Replace the existing sessionid" in asked["question"]
    assert saved["sessionid"] == "replacement-sid"

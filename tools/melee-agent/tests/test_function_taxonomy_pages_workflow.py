from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "taxonomy-pages.yml"


def test_taxonomy_pages_workflow_is_fork_only_and_deploys_pages_artifact() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "github.repository == 'itsgrimetime/melee'" in text
    assert "pages: write" in text
    assert "id-token: write" in text
    assert "actions/configure-pages@" in text
    assert "actions/upload-pages-artifact@" in text
    assert "actions/deploy-pages@" in text
    assert "rm -rf orig" in text
    assert "ln -s /orig orig" in text


def test_taxonomy_pages_workflow_generates_inventory_then_dashboard() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    inventory = "python3 tools/function_taxonomy_inventory.py"
    dashboard = "python3 tools/function_taxonomy_dashboard.py"
    assert inventory in text
    assert dashboard in text
    assert text.index(inventory) < text.index(dashboard)
    assert "build/function-taxonomy" in text
    assert "_site/taxonomy" in text

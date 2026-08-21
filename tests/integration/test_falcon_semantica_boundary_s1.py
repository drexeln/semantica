from __future__ import annotations

from pathlib import Path

from examples.falcon.porsche_decision_s1 import DECISION_STORAGE_RULE

ROOT = Path(__file__).resolve().parents[2]


def test_falcon_terms_do_not_enter_semantica_core() -> None:
    forbidden_terms = [
        "porsche_tender_001",
        "Porsche Tender",
        "Falcon quest",
        "Consultant XP",
        "Godot state",
    ]
    offenders = []
    for path in (ROOT / "semantica").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for term in forbidden_terms:
            if term in text:
                offenders.append(f"{path.relative_to(ROOT)}: {term}")
    assert offenders == []


def test_decision_storage_rule_excludes_routine_agent_steps() -> None:
    assert "requires_human_approval" in DECISION_STORAGE_RULE["store_decision_when"]
    assert "changes_artifact" in DECISION_STORAGE_RULE["store_decision_when"]
    assert "rejects_meaningful_alternative" in DECISION_STORAGE_RULE["store_decision_when"]
    assert "routine_agent_step" in DECISION_STORAGE_RULE["do_not_store"]
    assert "transient_execution_log" in DECISION_STORAGE_RULE["do_not_store"]


def test_boundary_readme_documents_allowed_surfaces_and_rule() -> None:
    readme = (ROOT / "examples" / "falcon" / "README.md").read_text(encoding="utf-8")
    assert "examples/falcon/porsche_decision_fixture.json" in readme
    assert "tests/integration/test_falcon_*_s1.py" in readme
    assert "DecisionStorageRule" in readme
    assert "Do not store routine agent steps" in readme

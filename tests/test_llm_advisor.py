"""LLM wrapper (offline) and the advisor's rule-based outputs."""
from __future__ import annotations

import pytest

from parity_agent.advisor import choose_canonical
from parity_agent.llm import MOCK_BANNER, MockLLM, get_llm, parse_json_object


def test_mock_when_model_is_mock(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "mock")
    assert get_llm().is_mock


def test_mock_when_no_key(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-5")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm = get_llm()
    assert llm.is_mock and llm.describe() == MOCK_BANNER


def test_real_client_selected_with_key(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used")
    llm = get_llm()
    assert not llm.is_mock and llm.model == "anthropic/claude-sonnet-4-5"


def test_mock_delegates_to_rule_function():
    llm = MockLLM()
    assert llm.complete_json("t", "s", "p", {"x": 2}, lambda p: {"y": p["x"] * 2}) == {"y": 4}
    assert llm.usage.calls == 1


def test_parse_json_object_tolerates_fences():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json_object("no json here")


@pytest.mark.parametrize(
    ("a", "b", "kind", "expected"),
    [
        ("Pay Bill", "Billing & Payments", "page", "Pay Bill"),
        ("Cart", "Bag", "page", "Cart"),
        ("Plans", "Plans & Pricing", "page", "Plans"),
        ("my account", "Profile", "page", "My Account"),
        ("Review Payment", "Continue", "cta", "Review Payment"),
    ],
)
def test_canonical_name_rules(a, b, kind, expected):
    assert choose_canonical(a, b, kind)[0] == expected


def test_advice_annotates_findings(audit):
    renames = [f for f in audit.findings if f.category == "page_name"]
    assert renames and all("canonical_name" in f.extra for f in renames)
    actions = {r.action for r in audit.advice.recommendations}
    assert {"rename", "redesign"} <= actions
    assert "differences" in audit.advice.executive_summary

"""Evaluation against the planted ground truth."""
from __future__ import annotations

from parity_agent.config import PLANTED_DIFFERENCES
from parity_agent.evaluate import evaluate, load_planted

RECALL_THRESHOLD = 0.9
PRECISION_THRESHOLD = 0.9


def test_ground_truth_is_well_formed():
    planted = load_planted(PLANTED_DIFFERENCES)
    assert len(planted) >= 15
    assert len({p["id"] for p in planted}) == len(planted)
    assert {p["category"] for p in planted} == {"page_name", "chatbot", "component", "cta", "flow", "coverage"}


def test_recall_and_precision_above_threshold(audit):
    ev = audit.evaluation
    assert ev is not None
    assert ev.overall.recall >= RECALL_THRESHOLD, ev.missed
    assert ev.overall.precision >= PRECISION_THRESHOLD, ev.false_positives
    for score in ev.per_category:
        assert score.recall >= 0.75, (score.category, ev.missed)


def test_eval_penalises_missing_and_extra_findings(audit):
    findings = [f for f in audit.findings if f.category != "chatbot"]
    ev = evaluate(findings, PLANTED_DIFFERENCES)
    chat = next(s for s in ev.per_category if s.category == "chatbot")
    assert chat.recall == 0.0 and chat.fn == 4
    assert ev.overall.recall < 1.0

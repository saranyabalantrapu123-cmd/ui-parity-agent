"""Happy-path flow runner (scripted + goal-driven)."""
from __future__ import annotations

from parity_agent.config import DEFAULT_FLOWS
from parity_agent.flows import _mock_choose, load_flows


def test_flows_yaml_loads():
    specs = {s.id: s for s in load_flows(DEFAULT_FLOWS)}
    assert set(specs) == {"buy-phone", "pay-bill", "switch-plan"}
    assert specs["switch-plan"].mode == "goal"


def test_buy_phone_step_counts(audit):
    runs = audit.flow_runs["buy-phone"]
    assert runs["web"].success and runs["app"].success
    assert runs["web"].step_count == 4
    assert runs["app"].step_count == 6
    assert [s.page_name for s in runs["app"].steps][2:4] == ["Protect Your Device", "Bag"]
    assert runs["web"].steps[-1].page_name == runs["app"].steps[-1].page_name == "Order Confirmed"


def test_pay_bill_step_names(audit):
    runs = audit.flow_runs["pay-bill"]
    assert [s.page_name for s in runs["web"].steps] == ["Pay Bill", "Review Payment", "Payment Received"]
    assert [s.page_name for s in runs["app"].steps] == ["Billing & Payments", "Confirm Payment", "Payment Received"]


def test_goal_mode_reaches_success_on_both(audit):
    runs = audit.flow_runs["switch-plan"]
    for run in runs.values():
        assert run.success, run.error
        assert run.step_count == 3
        assert "Unlimited Plus" in run.steps[1].action


def test_mock_navigator_prefers_goal_keywords():
    payload = {
        "goal": "Switch my plan to Unlimited Plus",
        "candidates": [
            {"index": 0, "label": "Select Plan", "context": "Essentials"},
            {"index": 1, "label": "Select Plan", "context": "Unlimited Plus"},
            {"index": 2, "label": "Shop Phones", "context": ""},
        ],
    }
    assert _mock_choose(payload)["index"] == 1

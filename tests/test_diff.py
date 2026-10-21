"""Deterministic diff engine on hand-built snapshots."""
from __future__ import annotations

from parity_agent.diff import (
    compute_findings,
    diff_chatbot,
    diff_components,
    diff_ctas,
    diff_flows,
)
from parity_agent.models import (
    ChatWidget,
    Component,
    FlowResult,
    FlowStep,
    PagePair,
    PageSnapshot,
)


def snap(platform, path, h1, comps, chat=None):
    return PageSnapshot(
        platform=platform, url=f"http://{platform}.test{path}", path=path, title=h1, h1=h1, nav_labels=[],
        components=comps, chat=chat or ChatWidget(present=False),
    )


def C(id, kind, name, parent=None, context="", fields=None):
    return Component(id=id, kind=kind, name=name, parent=parent, context=context, fields=fields or [])


def test_cta_relabels_are_grouped_by_label_pair():
    web = snap("web", "/plans", "Plans", [C(1, "card", "A"), C(2, "cta", "Select Plan", 1, "A"),
                                          C(3, "card", "B"), C(4, "cta", "Select Plan", 3, "B")])
    app = snap("app", "/plans", "Plans", [C(1, "card", "A"), C(2, "cta", "Choose Plan", 1, "A"),
                                          C(3, "card", "B"), C(4, "cta", "Choose Plan", 3, "B")])
    findings = diff_ctas(PagePair(web, app, 1.0, "heuristic"), set(), set())
    assert len(findings) == 1
    assert findings[0].subject == "Select Plan -> Choose Plan"
    assert findings[0].extra["occurrences"] == 2


def test_missing_component_suppresses_nested_items():
    web = snap("web", "/p", "P", [C(1, "region", "Trade-in estimator"), C(2, "form", "Trade-in form", 1, "Trade-in estimator", ["Model"]),
                                  C(3, "cta", "Estimate", 2, "Trade-in form"), C(4, "cta", "Buy", None, "")])
    app = snap("app", "/p", "P", [C(1, "cta", "Buy")])
    pair = PagePair(web, app, 1.0, "heuristic")
    comp, web_skip, app_skip = diff_components(pair)
    assert [f.subject for f in comp] == ["Trade-in estimator (section)"]
    assert comp[0].severity == "high"  # contains a form / CTA
    assert diff_ctas(pair, web_skip, app_skip) == []


def test_form_field_difference():
    web = snap("web", "/c", "C", [C(1, "form", "Checkout", fields=["Name", "Promo code"])])
    app = snap("app", "/c", "C", [C(1, "form", "Checkout", fields=["Name"])])
    comp, _, _ = diff_components(PagePair(web, app, 1.0, "heuristic"))
    assert len(comp) == 1 and comp[0].subject.startswith("Promo code field") and comp[0].severity == "low"


def test_chatbot_presence_and_position():
    fbr = ChatWidget(present=True, position="floating-bottom-right")
    fbl = ChatWidget(present=True, position="floating-bottom-left")
    hdr = ChatWidget(present=True, position="header")
    absent = ChatWidget(present=False)
    mk = lambda w, a: PagePair(snap("web", "/", "H", [], w), snap("app", "/", "H", [], a), 1.0, "heuristic")  # noqa: E731
    assert diff_chatbot(mk(fbr, fbr)) == []
    assert diff_chatbot(mk(absent, absent)) == []
    missing = diff_chatbot(mk(fbr, absent))[0]
    assert missing.severity == "high" and missing.action == "add-component"
    assert diff_chatbot(mk(fbr, hdr))[0].severity == "medium"
    assert diff_chatbot(mk(fbr, fbl))[0].severity == "low"


def _run(platform, names, success=True):
    steps = [FlowStep(i + 1, "click", f"http://{platform}/{n}", f"/{n}", n) for i, n in enumerate(names)]
    return FlowResult("f", "Flow", platform, "scripted", success, steps)


def test_flow_step_count_and_names():
    counts = diff_flows({"f": {"web": _run("web", ["A", "B"]), "app": _run("app", ["A", "X", "B", "Y"])}}, [])
    assert len(counts) == 1 and counts[0].severity == "high" and counts[0].subject == "Step count: web 2 vs app 4"
    names = diff_flows({"f": {"web": _run("web", ["A", "Review"]), "app": _run("app", ["A", "Confirm"])}}, [])
    assert len(names) == 1 and names[0].subject == "Step names differ"
    broken = diff_flows({"f": {"web": _run("web", ["A"]), "app": _run("app", ["A"], success=False)}}, [])
    assert broken[0].subject == "Flow broken on app"


def test_identical_pages_produce_no_findings():
    comps = [C(1, "region", "Topics"), C(2, "card", "Billing", 1, "Topics"), C(3, "cta", "Go", 2, "Billing")]
    pair = PagePair(snap("web", "/s", "Support", comps), snap("app", "/s", "Support", comps), 1.0, "heuristic")
    assert compute_findings([pair], [], [], {}) == []


def test_findings_are_sorted_and_numbered(audit):
    ids = [f.id for f in audit.findings]
    assert ids == [f"F{i:03d}" for i in range(1, len(ids) + 1)]
    order = {"high": 0, "medium": 1, "low": 2}
    assert [order[f.severity] for f in audit.findings] == sorted(order[f.severity] for f in audit.findings)

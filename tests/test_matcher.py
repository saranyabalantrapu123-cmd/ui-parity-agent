"""Cross-platform page matching."""
from __future__ import annotations

from parity_agent.llm import MockLLM
from parity_agent.matcher import match_pages
from parity_agent.models import ChatWidget, Component, PageSnapshot

EXPECTED = {
    "/": "/",
    "/plans.html": "/plans.html",
    "/phones.html": "/devices.html",
    "/phones/nimbus-x15.html": "/devices/x15.html",
    "/cart.html": "/bag.html",
    "/checkout.html": "/checkout.html",
    "/pay-bill.html": "/billing.html",
    "/account.html": "/profile.html",
    "/support.html": "/support.html",
    "/plan-change.html": "/plan-change.html",
}


def test_demo_pairs(audit):
    got = {p.web.path: p.app.path for p in audit.pairs}
    assert got == EXPECTED
    assert [p.path for p in audit.unmatched_app] == ["/protection.html"]
    assert audit.unmatched_web == []


def test_llm_fallback_used_for_ambiguous_pages(audit):
    methods = {p.web.path: p.method for p in audit.pairs}
    assert methods["/support.html"] == "heuristic"
    assert "mock-llm" in methods.values()  # e.g. 'My Account' vs 'Profile' needs adjudication


def _page(platform: str, path: str, h1: str, comps: list[tuple[str, str]]) -> PageSnapshot:
    return PageSnapshot(
        platform=platform, url=f"http://{platform}.test{path}", path=path, title=h1, h1=h1, nav_labels=[],
        components=[Component(id=i + 1, kind=k, name=n) for i, (k, n) in enumerate(comps)],
        chat=ChatWidget(present=False),
    )


def test_content_beats_names():
    """Differently named pages with the same content are matched; unrelated pages are not."""
    web = [
        _page("web", "/pay-bill", "Pay Bill", [("form", "Payment form"), ("card", "Current balance"), ("cta", "Pay")]),
        _page("web", "/news", "Newsroom", [("card", "Press release")]),
    ]
    app = [
        _page("app", "/wallet", "Billing", [("form", "Payment form"), ("card", "Current balance"), ("cta", "Pay")]),
        _page("app", "/games", "Games", [("card", "Arcade")]),
    ]
    pairs, un_web, un_app = match_pages(web, app, MockLLM())
    assert [(p.web.path, p.app.path) for p in pairs] == [("/pay-bill", "/wallet")]
    assert [p.path for p in un_web] == ["/news"]
    assert [p.path for p in un_app] == ["/games"]

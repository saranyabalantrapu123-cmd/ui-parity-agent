"""Crawler behaviour on the bundled demo sites."""
from __future__ import annotations

from parity_agent.crawler import canonical_url


def test_canonical_url_collapses_index_and_query():
    assert canonical_url("http://x.test/index.html?a=1#top") == "http://x.test/"
    assert canonical_url("http://x.test/plan-change.html?plan=plus") == "http://x.test/plan-change.html"


def test_crawls_all_linked_pages_only(audit):
    web_paths = {p.path for p in audit.web_pages}
    app_paths = {p.path for p in audit.app_pages}
    assert web_paths == {
        "/", "/plans.html", "/phones.html", "/phones/nimbus-x15.html", "/cart.html", "/checkout.html",
        "/pay-bill.html", "/account.html", "/support.html", "/plan-change.html",
    }
    assert {"/devices.html", "/devices/x15.html", "/protection.html", "/bag.html", "/billing.html", "/profile.html"} <= app_paths
    assert len(app_paths) == 11
    # Pages reachable only by submitting a form are not crawled (flows cover them).
    assert "/order-confirmation.html" not in web_paths | app_paths


def test_device_emulation(audit):
    assert all(p.viewport["width"] == 1366 for p in audit.web_pages)
    assert all(p.viewport["width"] == 390 for p in audit.app_pages)


def test_page_capture_fields(audit):
    home = next(p for p in audit.web_pages if p.path == "/")
    assert home.name == "Home"
    assert home.h1 == "Welcome to Nimbus Wireless"
    assert {"Plans", "Shop Phones", "Pay Bill", "Support", "My Account", "Cart"} <= {n["label"] for n in home.nav_labels}
    kinds = {(c.kind, c.name) for c in home.components}
    assert ("banner", "Trade-in promotion") in kinds
    assert ("cta", "Explore Plans") in kinds
    assert ("card", "Nationwide 5G") in kinds


def test_forms_and_fields_captured(audit):
    checkout = next(p for p in audit.web_pages if p.path == "/checkout.html")
    form = next(c for c in checkout.components if c.kind == "form")
    assert form.fields == ["Full name", "Shipping address", "Card number", "Promo code"]


def test_screenshots_written(audit):
    for page in audit.web_pages + audit.app_pages:
        shot = audit.out_dir / page.screenshot
        assert shot.exists() and shot.stat().st_size > 5_000


def test_custom_urls_without_flows(tmp_path, browser):
    """Explicit --web/--app URLs: no default flows and no ground-truth eval, max_pages respected."""
    from parity_agent.llm import MockLLM
    from parity_agent.pipeline import run_audit
    from parity_agent.server import serve_demo_sites

    with serve_demo_sites() as (web, app):
        result = run_audit(web, app, max_pages=4, out_root=tmp_path, llm=MockLLM(), browser=browser)
    assert not result.demo and result.evaluation is None and result.flow_runs == {}
    assert len(result.web_pages) == 4 and len(result.app_pages) == 4
    assert (result.out_dir / "report.html").exists()

"""Chatbot detection and position normalisation."""
from __future__ import annotations

from pathlib import Path

import pytest

from parity_agent.chatbot import build_chat_widget, classify_position
from parity_agent.crawler import new_context, snapshot_page

VIEWPORT = {"width": 1000, "height": 800}
FIXTURE = Path(__file__).parent / "fixtures" / "chat_widgets.html"


@pytest.mark.parametrize(
    ("bbox", "fixed", "in_header", "expected"),
    [
        ({"x": 900, "y": 700, "width": 80, "height": 40, "viewport_y": 700}, True, False, "floating-bottom-right"),
        ({"x": 10, "y": 700, "width": 80, "height": 40, "viewport_y": 700}, True, False, "floating-bottom-left"),
        ({"x": 900, "y": 10, "width": 80, "height": 40, "viewport_y": 10}, True, False, "floating-top-right"),
        ({"x": 900, "y": 10, "width": 80, "height": 40, "viewport_y": 10}, False, True, "header"),
        ({"x": 100, "y": 2400, "width": 600, "height": 90, "viewport_y": 2400}, False, False, "inline"),
    ],
)
def test_classify_position(bbox, fixed, in_header, expected):
    assert classify_position(bbox, VIEWPORT, fixed=fixed, in_header=in_header) == expected


def test_floating_widget_is_preferred_over_inline():
    inline = {"bbox": {"x": 0, "y": 900, "width": 300, "height": 80}, "fixed": False, "in_header": False}
    floating = {"bbox": {"x": 900, "y": 700, "width": 60, "height": 60, "viewport_y": 700}, "fixed": True, "in_header": False}
    widget = build_chat_widget([inline, floating], VIEWPORT)
    assert widget.present and widget.position == "floating-bottom-right"


def test_no_candidates_means_absent():
    widget = build_chat_widget([], VIEWPORT)
    assert not widget.present and widget.position == "absent"


def test_demo_positions_detected(audit):
    web = {p.path: p.chat.position for p in audit.web_pages}
    app = {p.path: p.chat.position for p in audit.app_pages}
    assert web["/"] == app["/"] == "floating-bottom-right"
    assert web["/pay-bill.html"] == "inline"
    assert app["/devices.html"] == "header"
    assert app["/plans.html"] == "absent"
    assert web["/checkout.html"] == "absent" and app["/checkout.html"] == "floating-bottom-right"
    assert web["/support.html"] == app["/support.html"] == "inline"


def test_heuristic_detection_without_semantic_markup(browser):
    """A vendor iframe (no data- attributes) is found; a nav link mentioning chat is not."""
    context = new_context(browser, "web")
    page = context.new_page()
    page.set_content(FIXTURE.read_text())
    snap = snapshot_page(page, "web", None, None)
    context.close()
    assert snap.chat.present
    assert snap.chat.position == "floating-bottom-left"
    assert "intercom" in snap.chat.label.lower() or "frame" in snap.chat.selector_hint
    kinds = {(c.kind, c.name) for c in snap.components}
    assert ("card", "Fast setup") in kinds
    assert ("cta", "Get started") in kinds
    assert not any(c.kind == "banner" for c in snap.components)  # "hero-wrap" is not a banner token

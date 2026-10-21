"""Chatbot widget position normalisation.

The browser-side extractor reports every candidate chat widget with its bounding box and a few
layout facts. This module turns that raw geometry into one of a small set of normalised positions
so web and app placements can be compared even though the viewports differ in size.
"""
from __future__ import annotations

from typing import Any

from .models import ChatWidget

POSITIONS = (
    "floating-bottom-right",
    "floating-bottom-left",
    "floating-top-right",
    "floating-top-left",
    "header",
    "inline",
    "absent",
)


def classify_position(
    bbox: dict[str, float],
    viewport: dict[str, int],
    *,
    fixed: bool,
    in_header: bool,
) -> str:
    """Map a widget's geometry to a normalised position label.

    - Anything inside a <header>/role=banner is ``header``.
    - Fixed-position widgets are ``floating-<vertical>-<horizontal>``, decided by which viewport
      quadrant the widget's centre falls into.
    - Everything else lives in the document flow and is ``inline``.
    """
    if in_header:
        return "header"
    if fixed:
        vw = max(viewport.get("width", 1), 1)
        vh = max(viewport.get("height", 1), 1)
        top = bbox.get("viewport_y", bbox.get("y", 0.0))
        cx = bbox.get("x", 0.0) + bbox.get("width", 0.0) / 2
        cy = top + bbox.get("height", 0.0) / 2
        vertical = "bottom" if cy >= vh / 2 else "top"
        horizontal = "right" if cx >= vw / 2 else "left"
        return f"floating-{vertical}-{horizontal}"
    return "inline"


def build_chat_widget(candidates: list[dict[str, Any]], viewport: dict[str, int]) -> ChatWidget:
    """Pick the primary chat widget among detected candidates (floating launchers win)."""
    if not candidates:
        return ChatWidget(present=False)
    ranked = sorted(candidates, key=lambda c: (not c.get("fixed"), not c.get("in_header")))
    primary = ranked[0]
    position = classify_position(
        primary["bbox"], viewport, fixed=bool(primary.get("fixed")), in_header=bool(primary.get("in_header"))
    )
    return ChatWidget(
        present=True,
        position=position,
        label=primary.get("label", ""),
        selector_hint=primary.get("selector_hint", ""),
        bbox=primary["bbox"],
    )


def position_family(position: str) -> str:
    """Coarse grouping used for severity: floating vs header vs inline vs absent."""
    return "floating" if position.startswith("floating") else position

"""Typed data structures shared across the crawler, matcher, diff engine and reports."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

_TITLE_SEP = re.compile(r"\s*[|\u00b7]\s*|\s[-\u2013\u2014]\s")  # "Plans | Brand", "Plans - Brand"

SEVERITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Component:
    """A UI component found inside the page's main content area."""

    id: int
    kind: str  # banner | region | card | form | cta | heading
    name: str
    parent: int | None = None  # id of the enclosing component, if any
    context: str = ""  # name of the nearest enclosing named component (for CTA pairing)
    fields: list[str] = field(default_factory=list)  # form field labels (forms only)
    href: str | None = None  # link target (CTAs that are links)


@dataclass
class ChatWidget:
    """A detected AI chat assistant / chatbot entry point."""

    present: bool
    position: str = "absent"  # floating-bottom-right | floating-bottom-left | ... | header | inline | absent
    label: str = ""
    selector_hint: str = ""
    bbox: dict[str, float] | None = None


@dataclass
class PageSnapshot:
    platform: str
    url: str
    path: str
    title: str
    h1: str
    nav_labels: list[dict[str, str]]
    components: list[Component]
    chat: ChatWidget
    screenshot: str | None = None  # path relative to the report directory
    links: list[str] = field(default_factory=list)
    viewport: dict[str, int] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """The user-visible page name.

        H1 first, then the <title> before any brand suffix. Home pages use the title because their
        H1 is usually a marketing headline rather than a page name.
        """
        from_title = self.title.split("|")[0].split("·")[0].strip()
        if self.path == "/" and from_title:
            return from_title
        return self.h1 or from_title

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PagePair:
    """A web page matched to its app counterpart."""

    web: PageSnapshot
    app: PageSnapshot
    score: float
    method: str  # heuristic | llm | mock-llm


@dataclass
class FlowStep:
    index: int
    action: str  # human-readable action, e.g. 'click "Buy Now"'
    url: str
    path: str
    page_name: str


@dataclass
class FlowResult:
    flow_id: str
    flow_name: str
    platform: str
    mode: str  # scripted | goal
    success: bool
    steps: list[FlowStep]
    error: str | None = None

    @property
    def step_count(self) -> int:
        return len(self.steps)


@dataclass
class Finding:
    id: str
    category: str  # page_name | chatbot | component | cta | flow | coverage
    severity: str
    page: str  # human-readable page (or flow) label
    subject: str  # what differs, e.g. 'Promo banner' or 'Select Plan -> Choose Plan'
    description: str
    web_value: str = ""
    app_value: str = ""
    web_path: str | None = None
    app_path: str | None = None
    action: str = "redesign"  # rename | redesign | add-component
    proposed_fix: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

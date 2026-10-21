"""Happy-path flow definitions and the Playwright flow runner.

Two flow styles are supported in ``flows.yaml``:

* **scripted** - an explicit list of steps per platform (click by visible text/accessible name or CSS
  selector, optionally filling form fields first);
* **goal** - only a goal sentence and a start page; the runner explores the UI, letting the LLM pick
  the next element to click (offline: keyword-overlap scoring), until ``success_text`` appears.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import yaml
from playwright.sync_api import Browser, Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from rapidfuzz import fuzz

from .config import PACKAGE_DIR
from .crawler import canonical_url, new_context, url_path
from .llm import BaseLLM
from .models import FlowResult, FlowStep

log = logging.getLogger(__name__)

CANDIDATES_JS = (PACKAGE_DIR / "js" / "candidates.js").read_text()
PAGE_NAME_JS = "() => { const h = document.querySelector('h1'); return (h && h.innerText.trim()) || document.title; }"

PROGRESS_VERBS = {"confirm", "continue", "submit", "place", "pay", "next", "review", "checkout", "finish", "complete"}
STOPWORDS = {"my", "to", "the", "a", "an", "and", "for", "of", "i", "me", "want", "please", "new", "with", "on", "in"}

SAMPLE_VALUES = [
    (re.compile(r"name", re.I), "Alex Rivera"),
    (re.compile(r"address|street", re.I), "100 Market Street"),
    (re.compile(r"card", re.I), "4242424242424242"),
    (re.compile(r"e-?mail", re.I), "alex@example.com"),
    (re.compile(r"phone|mobile", re.I), "5550102040"),
    (re.compile(r"amount", re.I), "65.00"),
    (re.compile(r"zip|postal", re.I), "94105"),
]


@dataclass
class PlatformFlow:
    start: str
    steps: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FlowSpec:
    id: str
    name: str
    mode: str  # scripted | goal
    success_text: str
    web: PlatformFlow
    app: PlatformFlow
    goal: str = ""
    max_steps: int = 8
    description: str = ""

    def for_platform(self, platform: str) -> PlatformFlow:
        return self.web if platform == "web" else self.app


def load_flows(path: Path) -> list[FlowSpec]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    specs = []
    for f in raw.get("flows", []):
        specs.append(
            FlowSpec(
                id=f["id"],
                name=f.get("name", f["id"]),
                mode=f.get("mode", "scripted"),
                success_text=f.get("success_text", ""),
                goal=f.get("goal", ""),
                max_steps=int(f.get("max_steps", 8)),
                description=f.get("description", ""),
                web=PlatformFlow(f["web"].get("start", "/"), f["web"].get("steps", [])),
                app=PlatformFlow(f["app"].get("start", "/"), f["app"].get("steps", [])),
            )
        )
    return specs


# ---------------------------------------------------------------------------- browser helpers
def _locate(page: Page, step: dict[str, Any]) -> Locator:
    if step.get("selector"):
        return page.locator(step["selector"]).filter(visible=True).first
    text = str(step["click"])
    for role in ("link", "button"):
        loc = page.get_by_role(role, name=text, exact=True).filter(visible=True)
        if loc.count():
            return loc.first
    return page.get_by_text(text, exact=True).filter(visible=True).first


def _fill(page: Page, fields: dict[str, Any]) -> None:
    for label, value in fields.items():
        target = page.get_by_label(str(label), exact=True).first
        if target.evaluate("el => el.tagName") == "SELECT":
            target.select_option(label=str(value))
        else:
            target.fill(str(value))


def _autofill_required(page: Page) -> None:
    """Fill empty required inputs with plausible sample data (goal-mode only)."""
    fields = page.evaluate(
        """() => [...document.querySelectorAll('input[required], textarea[required]')]
            .filter(i => !i.value && i.offsetParent !== null)
            .map(i => ({id: i.id, label: (i.labels && i.labels[0] ? i.labels[0].innerText : i.name || i.placeholder || '')}))"""
    )
    for f in fields:
        value = next((v for rx, v in SAMPLE_VALUES if rx.search(f["label"])), "test")
        if f["id"]:
            page.locator(f"#{f['id']}").fill(value)


def _click_and_wait(page: Page, locator: Locator) -> None:
    before = page.url
    locator.click()
    try:
        page.wait_for_url(lambda u: u != before, timeout=4000)
    except PlaywrightTimeout:
        pass  # in-page actions (e.g. opening a panel) do not navigate
    page.wait_for_load_state("load")


def _record(page: Page, index: int, action: str) -> FlowStep:
    return FlowStep(index, action, canonical_url(page.url), url_path(page.url), page.evaluate(PAGE_NAME_JS))


def _succeeded(page: Page, success_text: str) -> bool:
    if not success_text:
        return True
    body = page.evaluate("() => document.body.innerText")
    return success_text.lower() in body.lower()


# ---------------------------------------------------------------------------- goal navigation
def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w not in STOPWORDS}


def _mock_choose(payload: dict[str, Any]) -> dict[str, Any]:
    """Keyword-overlap navigator: label overlap x2, context overlap x1, bonus for 'progress' verbs."""
    goal = _tokens(payload["goal"])
    best, best_score = None, float("-inf")
    for cand in payload["candidates"]:
        label = _tokens(cand["label"])
        score = 2 * len(label & goal) + len(_tokens(cand["context"]) & goal)
        first = cand["label"].split()[0].lower() if cand["label"].split() else ""
        if first in PROGRESS_VERBS:
            score += 1.5
        score += fuzz.partial_ratio(payload["goal"].lower(), cand["label"].lower()) / 200
        if score > best_score:
            best, best_score = cand, score
    return {"index": best["index"] if best else None, "reason": "highest keyword overlap with the goal"}


CHOOSE_SYSTEM = "You are a QA agent completing a user goal in a web UI by clicking one element at a time."
CHOOSE_PROMPT = (
    "Pick the single element to click next that makes the most progress toward the goal. "
    'Return {"index": <candidate index>, "reason": "<short>"}.'
)


def _run_goal(page: Page, spec: FlowSpec, llm: BaseLLM, steps: list[FlowStep]) -> None:
    visited = {canonical_url(page.url)}
    clicked: set[tuple[str, str]] = set()
    for i in range(1, spec.max_steps + 1):
        if _succeeded(page, spec.success_text):
            break
        here = canonical_url(page.url)
        candidates = [
            c
            for c in page.evaluate(CANDIDATES_JS)
            if (here, c["label"]) not in clicked and not (c["href"] and canonical_url(c["href"]) in visited)
        ]
        if not candidates:
            break
        payload = {
            "goal": spec.goal,
            "current_page": page.evaluate(PAGE_NAME_JS),
            "history": [s.page_name for s in steps],
            "candidates": candidates[:60],
        }
        choice = llm.complete_json("choose_action", CHOOSE_SYSTEM, CHOOSE_PROMPT, payload, _mock_choose)
        cand = next((c for c in candidates if c["index"] == choice.get("index")), None)
        if cand is None:
            break
        clicked.add((here, cand["label"]))
        if cand["submits"]:
            _autofill_required(page)
        _click_and_wait(page, page.locator(f'[data-parity-idx="{cand["index"]}"]'))
        visited.add(canonical_url(page.url))
        label = f'click "{cand["label"]}"' + (f' ({cand["context"]})' if cand["context"] else "")
        steps.append(_record(page, i, label))


def _run_scripted(page: Page, flow: PlatformFlow, steps: list[FlowStep]) -> None:
    for i, step in enumerate(flow.steps, start=1):
        parts = []
        if step.get("fill"):
            _fill(page, step["fill"])
            parts.append("fill " + ", ".join(step["fill"]))
        if step.get("click") or step.get("selector"):
            _click_and_wait(page, _locate(page, step))
            parts.append(f'click "{step.get("click") or step["selector"]}"')
        steps.append(_record(page, i, step.get("name") or " then ".join(parts)))


def run_flow(browser: Browser, spec: FlowSpec, platform: str, base_url: str, llm: BaseLLM) -> FlowResult:
    """Execute one flow on one platform in a fresh browser context."""
    flow = spec.for_platform(platform)
    context = new_context(browser, platform)
    page = context.new_page()
    steps: list[FlowStep] = []
    error = None
    try:
        page.goto(urljoin(base_url, flow.start), wait_until="load")
        if spec.mode == "goal":
            _run_goal(page, spec, llm, steps)
        else:
            _run_scripted(page, flow, steps)
        success = _succeeded(page, spec.success_text)
        if not success:
            error = f"Success text {spec.success_text!r} not found on final page {page.url}"
    except Exception as exc:  # a broken step is a finding, not a crash
        success = False
        error = f"{type(exc).__name__}: {exc}".splitlines()[0]
        log.warning("[%s] flow %s failed: %s", platform, spec.id, error)
    finally:
        context.close()
    return FlowResult(spec.id, spec.name, platform, spec.mode, success, steps, error)

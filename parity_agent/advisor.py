"""LLM layer: canonical names for mismatches, executive summary and prioritised recommendations.

Real-model path: structured JSON prompts through :mod:`parity_agent.llm`.
Offline path: deterministic rules (preferred vocabulary, then the shorter/clearer label; templated summary).
The deterministic findings are never altered here, only annotated with proposed fixes.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .llm import BaseLLM
from .models import SEVERITY_ORDER, Finding, FlowResult
from .textutil import norm, title_case

# Widely understood retail / telecom vocabulary, most specific first. If exactly one candidate
# name uses one of these terms, it wins; otherwise the shorter, clearer label wins.
PREFERRED_TERMS = [
    "pay bill", "checkout", "cart", "plans", "phones", "account", "support", "home", "order",
]
GENERIC_CTA = {"continue", "next", "submit", "ok", "go", "done", "proceed"}
SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}


def choose_canonical(a: str, b: str, kind: str = "page") -> tuple[str, str]:
    """Rule-based pick of the standard label between two variants. Returns (label, rationale)."""
    na, nb = norm(a), norm(b)
    if kind == "cta":
        ga, gb = na in GENERIC_CTA, nb in GENERIC_CTA
        if ga != gb:
            pick = b if ga else a
            return title_case(pick), f"'{pick}' says what happens next; generic verbs like '{a if ga else b}' do not."
    for term in PREFERRED_TERMS:
        pattern = rf"\b{re.escape(term)}\b"
        ina, inb = bool(re.search(pattern, na)), bool(re.search(pattern, nb))
        if ina != inb:
            pick = a if ina else b
            return title_case(pick), f"'{term}' is the more widely understood term."
    pick = min((a, b), key=lambda s: (len(s.split()), len(s)))
    return title_case(pick), "Shorter, clearer label."


def _mock_canonical(payload: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for item in payload["items"]:
        label, why = choose_canonical(item["web"], item["app"], item["kind"])
        out[item["finding_id"]] = {"canonical": label, "rationale": why}
    return {"names": out}


CANONICAL_SYSTEM = (
    "You are a UX content strategist standardising page names and button labels across a company's "
    "website and mobile app. Prefer plain, widely understood, action-oriented wording in Title Case."
)
CANONICAL_PROMPT = (
    "For each item choose ONE standard label to use on both platforms. It may be one of the two variants "
    "or a better third option. Return "
    '{"names": {"<finding_id>": {"canonical": "<label>", "rationale": "<one sentence>"}}}.'
)


@dataclass
class Recommendation:
    priority: int
    page: str
    action: str  # rename | redesign | add-component
    finding_ids: list[str]
    rationale: str


@dataclass
class Advice:
    executive_summary: str
    recommendations: list[Recommendation] = field(default_factory=list)


def propose_canonical_names(findings: list[Finding], llm: BaseLLM) -> None:
    """Annotate page_name and CTA-relabel findings with a proposed standard label (in place)."""
    items = [
        {"finding_id": f.id, "kind": "page" if f.category == "page_name" else "cta", "web": f.web_value,
         "app": f.app_value, "page": f.page}
        for f in findings
        if f.category == "page_name" or (f.category == "cta" and f.action == "rename")
    ]
    if not items:
        return
    names = llm.complete_json(
        "canonical_names", CANONICAL_SYSTEM, CANONICAL_PROMPT, {"items": items}, _mock_canonical
    ).get("names", {})
    for f in findings:
        choice = names.get(f.id)
        if not choice:
            continue
        canonical = choice["canonical"]
        f.extra["canonical_name"] = canonical
        f.extra["canonical_rationale"] = choice.get("rationale", "")
        what = "page" if f.category == "page_name" else "CTA"
        f.proposed_fix = (
            f"Rename the {what} to '{canonical}' on both platforms (web: '{f.web_value}', app: '{f.app_value}'). "
            f"{choice.get('rationale', '')}"
        ).strip()


def _page_action(finding_actions: list[str]) -> str:
    """Collapse a page's finding-level actions into one page-level action."""
    actions = Counter(finding_actions)
    if actions["redesign"] or actions["add-component"] >= 2:
        return "redesign"
    if actions["add-component"]:
        return "add-component"
    return "rename"


def _mock_summary(payload: dict[str, Any]) -> dict[str, Any]:
    findings = payload["findings"]
    by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in findings:
        by_page[f["page"]].append(f)
    recs = []
    for page, fs in by_page.items():
        weight = sum(SEVERITY_WEIGHT[f["severity"]] for f in fs)
        action = _page_action([f["action"] for f in fs])
        cats = sorted({f["category"].replace("_", " ") for f in fs})
        recs.append({
            "page": page, "action": action, "finding_ids": [f["id"] for f in fs], "weight": weight,
            "rationale": f"{len(fs)} difference(s) ({', '.join(cats)}); severity score {weight}.",
        })
    recs.sort(key=lambda r: (-r["weight"], r["page"]))
    for i, r in enumerate(recs, start=1):
        r["priority"] = i
        del r["weight"]

    sev = Counter(f["severity"] for f in findings)
    cat = Counter(f["category"] for f in findings)
    renames = sum(1 for r in recs if r["action"] == "rename")
    redesigns = sum(1 for r in recs if r["action"] == "redesign")
    adds = sum(1 for r in recs if r["action"] == "add-component")
    flow_lines = [
        f"'{fl['name']}' takes {fl['web_steps']} steps on web vs {fl['app_steps']} in the app"
        for fl in payload["flows"] if fl["web_steps"] != fl["app_steps"]
    ]
    parts = [
        f"Compared {payload['pairs']} matched pages and {len(payload['flows'])} happy-path flows across web and app "
        f"and found {len(findings)} differences ({sev['high']} high, {sev['medium']} medium, {sev['low']} low severity).",
        f"{cat['page_name']} pages carry different names on each platform, the AI assistant is inconsistent on "
        f"{cat['chatbot']} pages, and {cat['component'] + cat['cta']} component or call-to-action differences were found.",
    ]
    if flow_lines:
        parts.append("Biggest journey gap: " + "; ".join(flow_lines) + ".")
    parts.append(
        f"Recommended plan: rename {renames} page(s), redesign {redesigns} page(s) and add missing components to "
        f"{adds} page(s), starting with the highest-severity items below."
    )
    return {"executive_summary": " ".join(parts), "recommendations": recs}


SUMMARY_SYSTEM = (
    "You are a product design lead writing for executives. You turn a cross-platform UI parity audit "
    "into a short summary and a prioritised standardisation plan."
)
SUMMARY_PROMPT = (
    "Write a 3-5 sentence executive summary of the audit and a prioritised list of page-level "
    "recommendations. Each recommendation names the page, an action (exactly one of: rename, redesign, "
    "add-component), the finding ids it resolves, and a one-sentence rationale. Use 'redesign' when layout "
    "or journey changes are needed, 'rename' when only labels differ. Return "
    '{"executive_summary": "...", "recommendations": [{"priority": 1, "page": "...", "action": "...", '
    '"finding_ids": ["F001"], "rationale": "..."}]}.'
)


def summarise(findings: list[Finding], flow_runs: dict[str, dict[str, FlowResult]], pairs: int, llm: BaseLLM) -> Advice:
    payload = {
        "pairs": pairs,
        "findings": [
            {"id": f.id, "category": f.category, "severity": f.severity, "page": f.page, "subject": f.subject,
             "action": f.action}
            for f in sorted(findings, key=lambda f: SEVERITY_ORDER[f.severity])
        ],
        "flows": [
            {"id": fid, "name": runs["web"].flow_name, "web_steps": runs["web"].step_count,
             "app_steps": runs["app"].step_count}
            for fid, runs in flow_runs.items() if "web" in runs and "app" in runs
        ],
    }
    raw = llm.complete_json("summary", SUMMARY_SYSTEM, SUMMARY_PROMPT, payload, _mock_summary)
    valid_ids = {f.id for f in findings}
    recs = []
    for r in raw.get("recommendations", []):
        action = r.get("action", "redesign")
        recs.append(
            Recommendation(
                priority=int(r.get("priority", len(recs) + 1)),
                page=str(r.get("page", "")),
                action=action if action in ("rename", "redesign", "add-component") else "redesign",
                finding_ids=[i for i in r.get("finding_ids", []) if i in valid_ids],
                rationale=str(r.get("rationale", "")),
            )
        )
    recs.sort(key=lambda r: r.priority)
    return Advice(executive_summary=str(raw.get("executive_summary", "")), recommendations=recs)

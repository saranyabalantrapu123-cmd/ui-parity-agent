"""Deterministic diff engine: turns matched pages + flow runs into categorised, severity-ranked findings.

Categories
----------
page_name  - the same page carries different names (H1 / nav label)
chatbot    - AI assistant present on one platform only, or placed differently
component  - a banner/section/card/form (or a form field) exists on one platform only
cta        - the same call to action is labelled differently, or is missing
flow       - a happy-path flow takes a different number of steps, uses different step names, or breaks
coverage   - a page exists on one platform only
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from .chatbot import position_family
from .models import (
    SEVERITY_ORDER,
    Component,
    Finding,
    FlowResult,
    PagePair,
    PageSnapshot,
)
from .textutil import norm

STRUCTURAL_KINDS = ("banner", "region", "card", "form")
KIND_LABEL = {"banner": "banner", "region": "section", "card": "card", "form": "form"}


def _page_label(pair: PagePair) -> str:
    if norm(pair.web.name) == norm(pair.app.name):
        return pair.web.name
    return f"{pair.web.name} / {pair.app.name}"


def _finding(pair: PagePair | None, **kw: object) -> Finding:
    base: dict[str, object] = {}
    if pair is not None:
        base = {"page": _page_label(pair), "web_path": pair.web.path, "app_path": pair.app.path}
    base.update(kw)
    return Finding(id="", **base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------- page names
def diff_page_name(pair: PagePair) -> list[Finding]:
    if norm(pair.web.name) == norm(pair.app.name):
        return []
    web_nav = _nav_label_for(pair.web)
    app_nav = _nav_label_for(pair.app)
    nav_note = f" Navigation labels: web '{web_nav}', app '{app_nav}'." if web_nav or app_nav else ""
    return [
        _finding(
            pair,
            category="page_name",
            severity="medium",
            subject="Page name",
            description=f"Same page is called '{pair.web.name}' on web but '{pair.app.name}' in the app.{nav_note}",
            web_value=pair.web.name,
            app_value=pair.app.name,
            action="rename",
            proposed_fix="Standardise on one page name across platforms.",
            extra={"web_nav_label": web_nav, "app_nav_label": app_nav},
        )
    ]


def _nav_label_for(page: PageSnapshot) -> str:
    return next((n["label"] for n in page.nav_labels if n["href"] == page.url), "")


# ---------------------------------------------------------------------------- chatbot
def diff_chatbot(pair: PagePair) -> list[Finding]:
    w, a = pair.web.chat, pair.app.chat
    if not w.present and not a.present:
        return []
    if w.present != a.present:
        has, lacks = ("web", "app") if w.present else ("app", "web")
        where = (w if w.present else a).position
        return [
            _finding(
                pair,
                category="chatbot",
                severity="high",
                subject=f"AI assistant missing on {lacks}",
                description=f"The AI chat assistant is available on {has} ({where}) but missing on {lacks}.",
                web_value=w.position,
                app_value=a.position,
                action="add-component",
                proposed_fix=f"Add the assistant to the {lacks} page, placed {where} to match {has}.",
            )
        ]
    if w.position != a.position:
        same_family = position_family(w.position) == position_family(a.position)
        return [
            _finding(
                pair,
                category="chatbot",
                severity="low" if same_family else "medium",
                subject="AI assistant position",
                description=f"The AI chat assistant sits {w.position} on web but {a.position} in the app.",
                web_value=w.position,
                app_value=a.position,
                action="redesign",
                proposed_fix="Agree on one assistant placement pattern for this page type and apply it on both platforms.",
            )
        ]
    return []


# ---------------------------------------------------------------------------- components
def _structural(page: PageSnapshot) -> dict[tuple[str, str], Component]:
    out: dict[tuple[str, str], Component] = {}
    for c in page.components:
        if c.kind in STRUCTURAL_KINDS:
            out.setdefault((c.kind, norm(c.name)), c)
    return out


def _ancestors(comp: Component, by_id: dict[int, Component]) -> Iterable[Component]:
    parent = comp.parent
    while parent is not None and parent in by_id:
        yield by_id[parent]
        parent = by_id[parent].parent


def _has_interactive_children(comp: Component, page: PageSnapshot) -> bool:
    by_id = {c.id: c for c in page.components}
    return any(
        c.kind in ("cta", "form") and any(anc.id == comp.id for anc in _ancestors(c, by_id))
        for c in page.components
    )


def _orphans(page: PageSnapshot, keys: set[tuple[str, str]]) -> tuple[list[Component], set[int]]:
    """Components whose key is in ``keys`` and that are not nested in another such component.

    Returns (top-level components, ids of every component inside them) so nested CTAs/cards/forms
    are not reported a second time.
    """
    by_id = {c.id: c for c in page.components}
    flagged = {c.id for c in page.components if c.kind in STRUCTURAL_KINDS and (c.kind, norm(c.name)) in keys}
    top = [c for c in page.components if c.id in flagged and not any(a.id in flagged for a in _ancestors(c, by_id))]
    covered = {c.id for c in page.components if c.id in flagged or any(a.id in flagged for a in _ancestors(c, by_id))}
    return top, covered


def diff_components(pair: PagePair) -> tuple[list[Finding], set[int], set[int]]:
    """Missing/extra structural components and missing form fields.

    Returns findings plus the ids of web/app components already covered by a finding (so the CTA
    diff can skip buttons that live inside a missing component).
    """
    web_keys, app_keys = _structural(pair.web), _structural(pair.app)
    only_web = set(web_keys) - set(app_keys)
    only_app = set(app_keys) - set(web_keys)
    web_top, web_covered = _orphans(pair.web, only_web)
    app_top, app_covered = _orphans(pair.app, only_app)
    findings: list[Finding] = []
    for comps, page, has, lacks in ((web_top, pair.web, "web", "app"), (app_top, pair.app, "app", "web")):
        for c in comps:
            interactive = _has_interactive_children(c, page) or c.kind == "form"
            findings.append(
                _finding(
                    pair,
                    category="component",
                    severity="high" if interactive else "medium",
                    subject=f"{c.name} ({KIND_LABEL[c.kind]})",
                    description=f"'{c.name}' {KIND_LABEL[c.kind]} exists on {has} but is missing on {lacks}.",
                    web_value="present" if has == "web" else "missing",
                    app_value="present" if has == "app" else "missing",
                    action="add-component",
                    proposed_fix=f"Add the '{c.name}' {KIND_LABEL[c.kind]} to the {lacks} page, or remove it from {has} if it is intentionally platform-specific.",
                    extra={"kind": c.kind, "only_on": has},
                )
            )
    # Form fields of forms present on both sides.
    for key in set(web_keys) & set(app_keys):
        if key[0] != "form":
            continue
        wf, af = web_keys[key].fields, app_keys[key].fields
        wn, an = {norm(f): f for f in wf}, {norm(f): f for f in af}
        for missing_from, src, other in (("app", wn, an), ("web", an, wn)):
            for nf, label in src.items():
                if nf in other:
                    continue
                has = "web" if missing_from == "app" else "app"
                findings.append(
                    _finding(
                        pair,
                        category="component",
                        severity="low",
                        subject=f"{label} field ({web_keys[key].name})",
                        description=f"'{web_keys[key].name}' has a '{label}' field on {has} but not on {missing_from}.",
                        web_value="present" if has == "web" else "missing",
                        app_value="present" if has == "app" else "missing",
                        action="add-component",
                        proposed_fix=f"Add the '{label}' field to the {missing_from} form (or document why it differs).",
                        extra={"kind": "form-field", "only_on": has},
                    )
                )
    return findings, web_covered, app_covered


# ---------------------------------------------------------------------------- CTAs
def diff_ctas(pair: PagePair, web_skip: set[int], app_skip: set[int]) -> list[Finding]:
    web = [c for c in pair.web.components if c.kind == "cta" and c.id not in web_skip]
    app = [c for c in pair.app.components if c.kind == "cta" and c.id not in app_skip]

    # 1) Exact label matches (multiset).
    app_left = list(app)
    web_left: list[Component] = []
    for c in web:
        hit = next((x for x in app_left if norm(x.name) == norm(c.name)), None)
        if hit is not None:
            app_left.remove(hit)
        else:
            web_left.append(c)

    # 2) Same context (card/section/form) but different label -> relabelled CTA.
    relabels: Counter[tuple[str, str]] = Counter()
    contexts: dict[tuple[str, str], list[str]] = defaultdict(list)
    still_web: list[Component] = []
    for c in web_left:
        hit = next((x for x in app_left if norm(x.context) == norm(c.context)), None)
        if hit is None:
            still_web.append(c)
            continue
        app_left.remove(hit)
        relabels[(c.name, hit.name)] += 1
        contexts[(c.name, hit.name)].append(c.context or "page")

    findings = [
        _finding(
            pair,
            category="cta",
            severity="medium",
            subject=f"{w} -> {a}",
            description=f"Call to action labelled '{w}' on web but '{a}' in the app"
            + (f" ({n} occurrences: {', '.join(contexts[(w, a)])})." if n > 1 else f" (in {contexts[(w, a)][0]})."),
            web_value=w,
            app_value=a,
            action="rename",
            proposed_fix="Use one CTA label on both platforms (prefer the clearer, action-first wording).",
            extra={"occurrences": n},
        )
        for (w, a), n in relabels.items()
    ]
    # 3) Leftovers: CTA exists on one side only.
    for comps, has, lacks in ((still_web, "web", "app"), (app_left, "app", "web")):
        for c in comps:
            findings.append(
                _finding(
                    pair,
                    category="cta",
                    severity="medium",
                    subject=f"{c.name} (missing on {lacks})",
                    description=f"CTA '{c.name}' exists on {has} but has no counterpart on {lacks}.",
                    web_value=c.name if has == "web" else "",
                    app_value=c.name if has == "app" else "",
                    action="add-component",
                    proposed_fix=f"Add the '{c.name}' action to {lacks} or confirm it is intentionally {has}-only.",
                )
            )
    return findings


# ---------------------------------------------------------------------------- coverage
def diff_coverage(unmatched_web: list[PageSnapshot], unmatched_app: list[PageSnapshot]) -> list[Finding]:
    findings = []
    for pages, has, lacks in ((unmatched_web, "web", "app"), (unmatched_app, "app", "web")):
        for p in pages:
            findings.append(
                Finding(
                    id="",
                    category="coverage",
                    severity="medium",
                    page=p.name,
                    subject=f"{has.capitalize()}-only page",
                    description=f"'{p.name}' ({p.path}) exists on {has} with no matching {lacks} page.",
                    web_value=p.name if has == "web" else "",
                    app_value=p.name if has == "app" else "",
                    web_path=p.path if has == "web" else None,
                    app_path=p.path if has == "app" else None,
                    action="redesign",
                    proposed_fix=f"Decide whether '{p.name}' belongs in the shared journey: add it to {lacks} or fold it into an existing {has} page.",
                )
            )
    return findings


# ---------------------------------------------------------------------------- flows
def diff_flows(flow_runs: dict[str, dict[str, FlowResult]], pairs: list[PagePair]) -> list[Finding]:
    matched = {(p.web.path, p.app.path) for p in pairs}
    findings: list[Finding] = []
    for flow_id, runs in flow_runs.items():
        web, app = runs.get("web"), runs.get("app")
        if web is None or app is None:
            continue
        label = f"Flow: {web.flow_name}"
        web_path = " > ".join(s.page_name for s in web.steps)
        app_path = " > ".join(s.page_name for s in app.steps)
        common = {"page": label, "web_value": web_path, "app_value": app_path, "extra": {"flow_id": flow_id}}
        broken = [r for r in (web, app) if not r.success]
        for r in broken:
            findings.append(
                Finding(
                    id="", category="flow", severity="high", subject=f"Flow broken on {r.platform}",
                    description=f"'{r.flow_name}' did not complete on {r.platform}: {r.error}",
                    action="redesign", proposed_fix="Fix the broken step so the happy path completes.", **common,
                )
            )
        if broken:
            continue
        if web.step_count != app.step_count:
            gap = abs(web.step_count - app.step_count)
            longer = "app" if app.step_count > web.step_count else "web"
            findings.append(
                Finding(
                    id="", category="flow", severity="high" if gap >= 2 else "medium",
                    subject=f"Step count: web {web.step_count} vs app {app.step_count}",
                    description=f"'{web.flow_name}' takes {web.step_count} steps on web and {app.step_count} in the app; "
                    f"the {longer} journey has {gap} extra step(s).",
                    action="redesign",
                    proposed_fix=f"Remove or merge the extra {longer} step(s) so both journeys take {min(web.step_count, app.step_count)} steps.",
                    **common,
                )
            )
            continue
        diffs = [
            (ws.page_name, as_.page_name)
            for ws, as_ in zip(web.steps, app.steps, strict=True)
            if norm(ws.page_name) != norm(as_.page_name) and (ws.path, as_.path) not in matched
        ]
        if diffs:
            findings.append(
                Finding(
                    id="", category="flow", severity="medium", subject="Step names differ",
                    description=f"'{web.flow_name}' has the same number of steps but different step names: "
                    + "; ".join(f"'{w}' vs '{a}'" for w, a in diffs) + ".",
                    action="rename",
                    proposed_fix="Use the same step names on both platforms so support docs and analytics line up.",
                    **common,
                )
            )
    return findings


# ---------------------------------------------------------------------------- entry point
def compute_findings(
    pairs: list[PagePair],
    unmatched_web: list[PageSnapshot],
    unmatched_app: list[PageSnapshot],
    flow_runs: dict[str, dict[str, FlowResult]],
) -> list[Finding]:
    findings: list[Finding] = []
    for pair in pairs:
        findings += diff_page_name(pair)
        findings += diff_chatbot(pair)
        comp_findings, web_skip, app_skip = diff_components(pair)
        findings += comp_findings
        findings += diff_ctas(pair, web_skip, app_skip)
    findings += diff_coverage(unmatched_web, unmatched_app)
    findings += diff_flows(flow_runs, pairs)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.category, f.page))
    for i, f in enumerate(findings, start=1):
        f.id = f"F{i:03d}"
    return findings

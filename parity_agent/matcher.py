"""Cross-platform page matching: URL path + name + content similarity, with LLM fallback.

Each web page is scored against each app page:

    score = 0.2 * path_similarity + 0.3 * name_similarity + 0.5 * content_similarity

Confident, unambiguous pairs are accepted greedily. Pages left over (low score or a close
runner-up) are sent to the LLM with their top candidates; offline, a rule-based adjudicator
accepts a candidate only when its content or its name clearly agrees.
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from .llm import BaseLLM
from .models import PagePair, PageSnapshot
from .textutil import norm, path_words

ACCEPT_SCORE = 0.62
MARGIN = 0.08
CANDIDATE_FLOOR = 0.30
W_PATH, W_NAME, W_CONTENT = 0.2, 0.3, 0.5


@dataclass
class Scored:
    score: float
    path_sim: float
    name_sim: float
    content_sim: float


def nav_label_index(pages: list[PageSnapshot]) -> dict[str, str]:
    """Map page URL -> the label navigation menus use for it (first one seen wins)."""
    index: dict[str, str] = {}
    for page in pages:
        for item in page.nav_labels:
            index.setdefault(item["href"], item["label"])
    return index


def content_signature(page: PageSnapshot) -> set[str]:
    """Set of 'kind:name' tokens for the main-content components (H1 excluded: names may differ)."""
    return {f"{c.kind}:{norm(c.name)}" for c in page.components if c.kind != "heading"}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def score_pair(web: PageSnapshot, app: PageSnapshot, web_nav: dict[str, str], app_nav: dict[str, str]) -> Scored:
    path_sim = fuzz.token_set_ratio(path_words(web.path), path_words(app.path)) / 100
    names_web = [norm(web.name)] + ([norm(web_nav[web.url])] if web.url in web_nav else [])
    names_app = [norm(app.name)] + ([norm(app_nav[app.url])] if app.url in app_nav else [])
    name_sim = max(fuzz.token_set_ratio(a, b) for a in names_web for b in names_app) / 100
    content_sim = _jaccard(content_signature(web), content_signature(app))
    score = W_PATH * path_sim + W_NAME * name_sim + W_CONTENT * content_sim
    return Scored(round(score, 3), round(path_sim, 3), round(name_sim, 3), round(content_sim, 3))


def _page_brief(page: PageSnapshot) -> dict[str, object]:
    return {
        "path": page.path,
        "name": page.name,
        "components": sorted(content_signature(page))[:25],
    }


def _mock_adjudicate(payload: dict) -> dict:
    """Rule-based adjudication: strongest content overlap wins, or an exact name match."""
    best = None
    for cand in payload["candidates"]:
        ok = cand["content_sim"] >= 0.5 or cand["name_sim"] >= 0.95
        if ok and (best is None or (cand["content_sim"], cand["score"]) > (best["content_sim"], best["score"])):
            best = cand
    if best is None:
        return {"app_path": None, "reason": "No candidate shares enough content or naming."}
    return {
        "app_path": best["page"]["path"],
        "reason": f"Content overlap {best['content_sim']:.2f}, name similarity {best['name_sim']:.2f}.",
    }


ADJUDICATE_SYSTEM = (
    "You match pages of a company's website to the equivalent screens of its mobile app. "
    "Pages may use different names (e.g. 'Pay Bill' vs 'Billing & Payments') but serve the same purpose."
)
ADJUDICATE_PROMPT = (
    "Decide which candidate app page (if any) is the same page as the web page. Consider purpose, "
    "components, forms and calls to action, not just the title. Return "
    '{"app_path": "<candidate path or null>", "reason": "<one sentence>"}.'
)


def match_pages(
    web_pages: list[PageSnapshot], app_pages: list[PageSnapshot], llm: BaseLLM
) -> tuple[list[PagePair], list[PageSnapshot], list[PageSnapshot]]:
    """Return (pairs, unmatched_web, unmatched_app)."""
    web_nav, app_nav = nav_label_index(web_pages), nav_label_index(app_pages)
    scores = {
        (w.path, a.path): score_pair(w, a, web_nav, app_nav) for w in web_pages for a in app_pages
    }
    web_by, app_by = {w.path: w for w in web_pages}, {a.path: a for a in app_pages}
    free_web, free_app = set(web_by), set(app_by)
    pairs: list[PagePair] = []

    # 1) Greedy acceptance of confident, unambiguous pairs.
    for (wp, ap), sc in sorted(scores.items(), key=lambda kv: -kv[1].score):
        if wp not in free_web or ap not in free_app or sc.score < ACCEPT_SCORE:
            continue
        runner_up = max(
            [scores[(wp, a)].score for a in free_app if a != ap]
            + [scores[(w, ap)].score for w in free_web if w != wp]
            + [0.0]
        )
        if sc.score - runner_up < MARGIN:
            continue
        pairs.append(PagePair(web_by[wp], app_by[ap], sc.score, "heuristic"))
        free_web.discard(wp)
        free_app.discard(ap)

    # 2) Ambiguous leftovers -> LLM (or rule-based) adjudication over the top candidates.
    for wp in sorted(free_web, key=lambda p: -max([scores[(p, a)].score for a in free_app] + [0])):
        candidates = sorted(
            (a for a in free_app if scores[(wp, a)].score >= CANDIDATE_FLOOR),
            key=lambda a: -scores[(wp, a)].score,
        )[:3]
        if not candidates:
            continue
        payload = {
            "web_page": _page_brief(web_by[wp]),
            "candidates": [
                {"page": _page_brief(app_by[a]), **scores[(wp, a)].__dict__} for a in candidates
            ],
        }
        answer = llm.complete_json("match_pages", ADJUDICATE_SYSTEM, ADJUDICATE_PROMPT, payload, _mock_adjudicate)
        chosen = answer.get("app_path")
        if chosen in candidates:
            method = "mock-llm" if llm.is_mock else "llm"
            pairs.append(PagePair(web_by[wp], app_by[chosen], scores[(wp, chosen)].score, method))
            free_web.discard(wp)
            free_app.discard(chosen)

    pairs.sort(key=lambda p: web_pages.index(p.web))
    unmatched_web = [w for w in web_pages if w.path in free_web]
    unmatched_app = [a for a in app_pages if a.path in free_app]
    return pairs, unmatched_web, unmatched_app

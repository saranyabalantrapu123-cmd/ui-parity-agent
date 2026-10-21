"""End-to-end orchestration: serve/crawl -> match -> run flows -> diff -> LLM advice -> reports (-> eval)."""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Browser

from .advisor import Advice, propose_canonical_names, summarise
from .config import DEFAULT_FLOWS, PLANTED_DIFFERENCES, REPORTS_DIR
from .crawler import browser_session, crawl
from .diff import compute_findings
from .evaluate import EvalResult, evaluate
from .flows import load_flows, run_flow
from .llm import BaseLLM, get_llm
from .matcher import match_pages
from .models import Finding, FlowResult, PagePair, PageSnapshot
from .report import write_reports
from .server import serve_demo_sites

log = logging.getLogger(__name__)


@dataclass
class AuditResult:
    out_dir: Path
    web_url: str
    app_url: str
    demo: bool
    web_pages: list[PageSnapshot]
    app_pages: list[PageSnapshot]
    pairs: list[PagePair]
    unmatched_web: list[PageSnapshot]
    unmatched_app: list[PageSnapshot]
    flow_runs: dict[str, dict[str, FlowResult]]
    findings: list[Finding]
    advice: Advice
    llm: BaseLLM
    generated_at: str
    evaluation: EvalResult | None = None
    files: dict[str, Path] = field(default_factory=dict)


@contextlib.contextmanager
def _targets(web_url: str | None, app_url: str | None) -> Iterator[tuple[str, str, bool]]:
    if web_url and app_url:
        yield web_url, app_url, False
        return
    if web_url or app_url:
        raise ValueError("Pass both --web and --app, or neither to audit the bundled demo sites.")
    with serve_demo_sites() as (web, app):
        yield web, app, True


def run_audit(
    web_url: str | None = None,
    app_url: str | None = None,
    *,
    flows_path: Path | None = None,
    max_pages: int = 30,
    out_root: Path = REPORTS_DIR,
    llm: BaseLLM | None = None,
    browser: Browser | None = None,
) -> AuditResult:
    """Run the whole audit. With no URLs, the bundled demo sites are served locally and evaluated.

    Pass ``browser`` to reuse an already-launched Chromium (Playwright's sync API allows only one
    driver per thread); otherwise one is launched for the duration of the run.
    """
    llm = llm or get_llm()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(out_root) / stamp
    suffix = 1
    while out_dir.exists():
        suffix += 1
        out_dir = Path(out_root) / f"{stamp}-{suffix}"
    out_dir.mkdir(parents=True)

    session = contextlib.nullcontext(browser) if browser is not None else browser_session()
    with _targets(web_url, app_url) as (web, app, demo), session as browser:
        log.info("Crawling web: %s", web)
        web_pages = crawl(browser, web, "web", out_dir, max_pages=max_pages)
        log.info("Crawling app: %s", app)
        app_pages = crawl(browser, app, "app", out_dir, max_pages=max_pages)

        pairs, unmatched_web, unmatched_app = match_pages(web_pages, app_pages, llm)
        log.info("Matched %d page pairs (%d web-only, %d app-only)", len(pairs), len(unmatched_web), len(unmatched_app))

        flow_file = flows_path or (DEFAULT_FLOWS if demo else None)
        flow_runs: dict[str, dict[str, FlowResult]] = {}
        if flow_file:
            for spec in load_flows(flow_file):
                flow_runs[spec.id] = {
                    platform: run_flow(browser, spec, platform, base, llm)
                    for platform, base in (("web", web), ("app", app))
                }
                log.info(
                    "Flow %s: web %d steps, app %d steps",
                    spec.id, flow_runs[spec.id]["web"].step_count, flow_runs[spec.id]["app"].step_count,
                )

    findings = compute_findings(pairs, unmatched_web, unmatched_app, flow_runs)
    propose_canonical_names(findings, llm)
    advice = summarise(findings, flow_runs, len(pairs), llm)

    result = AuditResult(
        out_dir=out_dir, web_url=web, app_url=app, demo=demo, web_pages=web_pages, app_pages=app_pages,
        pairs=pairs, unmatched_web=unmatched_web, unmatched_app=unmatched_app, flow_runs=flow_runs,
        findings=findings, advice=advice, llm=llm, generated_at=datetime.now().isoformat(timespec="seconds"),
    )
    if demo and PLANTED_DIFFERENCES.exists():
        result.evaluation = evaluate(findings, PLANTED_DIFFERENCES)
    result.files = write_reports(result)
    return result

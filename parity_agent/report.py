"""Report writers: report.md, self-contained report.html, findings.json, backlog.csv, pages.json."""
from __future__ import annotations

import base64
import csv
import io
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from .config import PACKAGE_DIR
from .models import Finding, FlowStep, PagePair

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers (avoids a cycle)
    from .pipeline import AuditResult

BACKLOG_COLUMNS = ["page", "issue", "proposed_fix", "action", "severity", "category", "finding_id"]


def _thumb_data_uri(path: Path, width: int, max_height: int = 2600) -> str | None:
    """Downscale a screenshot and return it as a base64 JPEG data URI (keeps report.html portable)."""
    if not path.exists():
        return None
    with Image.open(path) as img:
        img = img.convert("RGB")
        ratio = width / img.width
        img = img.resize((width, max(1, int(img.height * ratio))), Image.LANCZOS)
        if img.height > max_height:
            img = img.crop((0, 0, width, max_height))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=78, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _findings_for_pair(pair: PagePair, findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.web_path == pair.web.path and f.app_path == pair.app.path]


def _usage_line(result: AuditResult) -> str:
    u = result.llm.usage
    if result.llm.is_mock:
        return f"{u.calls} rule-based LLM-layer calls (offline mock, no tokens used)"
    return (
        f"{u.calls} calls to {result.llm.model}: {u.prompt_tokens:,} prompt + {u.completion_tokens:,} completion tokens, "
        f"est. ${u.cost_usd:.4f}"
    )


def build_findings_json(result: AuditResult) -> dict[str, Any]:
    return {
        "generated_at": result.generated_at,
        "web_url": result.web_url,
        "app_url": result.app_url,
        "llm": result.llm.describe(),
        "llm_usage": result.llm.usage.to_dict(),
        "summary": {
            "pages_web": len(result.web_pages),
            "pages_app": len(result.app_pages),
            "matched_pairs": len(result.pairs),
            "findings": len(result.findings),
            "by_severity": dict(Counter(f.severity for f in result.findings)),
            "by_category": dict(Counter(f.category for f in result.findings)),
        },
        "executive_summary": result.advice.executive_summary,
        "recommendations": [asdict(r) for r in result.advice.recommendations],
        "pairs": [
            {"web": p.web.path, "app": p.app.path, "web_name": p.web.name, "app_name": p.app.name,
             "score": p.score, "method": p.method}
            for p in result.pairs
        ],
        "unmatched_web": [p.path for p in result.unmatched_web],
        "unmatched_app": [p.path for p in result.unmatched_app],
        "flows": {
            fid: {plat: asdict(run) | {"step_count": run.step_count} for plat, run in runs.items()}
            for fid, runs in result.flow_runs.items()
        },
        "findings": [f.to_dict() for f in result.findings],
        "evaluation": result.evaluation.to_dict() if result.evaluation else None,
    }


def write_backlog(findings: list[Finding], path: Path) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=BACKLOG_COLUMNS)
        writer.writeheader()
        for f in findings:
            writer.writerow(
                {
                    "page": f.page,
                    "issue": f"[{f.category}] {f.description}",
                    "proposed_fix": f.proposed_fix,
                    "action": f.action,
                    "severity": f.severity,
                    "category": f.category,
                    "finding_id": f.id,
                }
            )


def _md_escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _md_step(step: FlowStep | None) -> str:
    return f"{_md_escape(step.action)} → **{_md_escape(step.page_name)}**" if step else "—"


def build_markdown(result: AuditResult) -> str:
    sev = Counter(f.severity for f in result.findings)
    out = [
        "# UI Parity Report",
        "",
        f"*Generated {result.generated_at}* · web `{result.web_url}` vs app `{result.app_url}`",
        "",
    ]
    if result.llm.is_mock:
        out += [f"> **{result.llm.describe()}**", ""]
    out += [
        f"**{len(result.web_pages)}** web pages · **{len(result.app_pages)}** app screens · "
        f"**{len(result.pairs)}** matched pairs · **{len(result.findings)}** findings "
        f"({sev['high']} high / {sev['medium']} medium / {sev['low']} low)",
        "",
        "## Executive summary",
        "",
        result.advice.executive_summary,
        "",
        "## Prioritised recommendations",
        "",
        "| # | Page | Action | Findings | Why |",
        "|---:|---|---|---|---|",
    ]
    for r in result.advice.recommendations:
        out.append(f"| {r.priority} | {_md_escape(r.page)} | **{r.action}** | {', '.join(r.finding_ids)} | {_md_escape(r.rationale)} |")
    out += ["", "## Findings", "", "| ID | Severity | Category | Page | Difference | Web | App | Proposed fix |",
            "|---|---|---|---|---|---|---|---|"]
    for f in result.findings:
        out.append(
            f"| {f.id} | {f.severity} | {f.category} | {_md_escape(f.page)} | {_md_escape(f.description)} | "
            f"{_md_escape(f.web_value)} | {_md_escape(f.app_value)} | {_md_escape(f.proposed_fix)} |"
        )
    if result.flow_runs:
        out += ["", "## Happy-path flows", ""]
        for runs in result.flow_runs.values():
            web, app = runs["web"], runs["app"]
            out += [f"### {web.flow_name} ({web.mode})", "", "| Step | Web | App |", "|---:|---|---|"]
            for i in range(max(web.step_count, app.step_count)):
                ws = web.steps[i] if i < web.step_count else None
                as_ = app.steps[i] if i < app.step_count else None
                out.append(f"| {i + 1} | {_md_step(ws)} | {_md_step(as_)} |")
            out += [f"| **Total** | **{web.step_count}** ({'ok' if web.success else 'FAILED'}) | "
                    f"**{app.step_count}** ({'ok' if app.success else 'FAILED'}) |", ""]
    out += ["## Page matching", "", "| Web page | App screen | Score | Method |", "|---|---|---:|---|"]
    for p in result.pairs:
        out.append(f"| {_md_escape(p.web.name)} (`{p.web.path}`) | {_md_escape(p.app.name)} (`{p.app.path}`) | {p.score:.2f} | {p.method} |")
    for p in result.unmatched_web:
        out.append(f"| {_md_escape(p.name)} (`{p.path}`) | — | | unmatched |")
    for p in result.unmatched_app:
        out.append(f"| — | {_md_escape(p.name)} (`{p.path}`) | | unmatched |")
    if result.evaluation:
        out += ["", "## Evaluation vs planted differences", "", result.evaluation.to_markdown()]
    out += ["", f"*LLM usage: {_usage_line(result)}*", ""]
    return "\n".join(out)


def build_html(result: AuditResult) -> str:
    env = Environment(
        loader=FileSystemLoader(PACKAGE_DIR / "templates"),
        autoescape=select_autoescape(["html", "j2"]),
    )
    pages = []
    for pair in result.pairs:
        pages.append(
            {
                "pair": pair,
                "findings": _findings_for_pair(pair, result.findings),
                "web_img": _thumb_data_uri(result.out_dir / pair.web.screenshot, 640) if pair.web.screenshot else None,
                "app_img": _thumb_data_uri(result.out_dir / pair.app.screenshot, 300) if pair.app.screenshot else None,
            }
        )
    unmatched = [
        {"page": p, "img": _thumb_data_uri(result.out_dir / p.screenshot, 300 if p.platform == "app" else 640)}
        for p in [*result.unmatched_web, *result.unmatched_app]
        if p.screenshot
    ]
    flows = []
    for fid, runs in result.flow_runs.items():
        web, app = runs["web"], runs["app"]
        flow_findings = [f for f in result.findings if f.extra.get("flow_id") == fid]
        flows.append({"id": fid, "web": web, "app": app, "findings": flow_findings,
                      "rows": max(web.step_count, app.step_count)})
    sev = Counter(f.severity for f in result.findings)
    cat = Counter(f.category for f in result.findings)
    actions = Counter(r.action for r in result.advice.recommendations)
    template = env.get_template("report.html.j2")
    return template.render(
        r=result,
        sev=sev,
        cat=cat,
        actions=actions,
        pages=pages,
        unmatched=unmatched,
        flows=flows,
        usage=_usage_line(result),
        categories=sorted(cat),
    )


def write_reports(result: AuditResult) -> dict[str, Path]:
    out = result.out_dir
    files = {
        "json": out / "findings.json",
        "md": out / "report.md",
        "html": out / "report.html",
        "csv": out / "standardization_backlog.csv",
        "pages": out / "pages.json",
    }
    files["json"].write_text(json.dumps(build_findings_json(result), indent=2))
    files["pages"].write_text(
        json.dumps({"web": [p.to_dict() for p in result.web_pages], "app": [p.to_dict() for p in result.app_pages]}, indent=2)
    )
    write_backlog(result.findings, files["csv"])
    files["md"].write_text(build_markdown(result))
    files["html"].write_text(build_html(result))
    if result.evaluation:
        files["eval"] = out / "eval.json"
        files["eval"].write_text(json.dumps(result.evaluation.to_dict(), indent=2))
    return files

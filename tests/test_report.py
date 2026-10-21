"""Report outputs."""
from __future__ import annotations

import csv
import json

from parity_agent.report import BACKLOG_COLUMNS


def test_all_outputs_written(audit):
    for key in ("json", "md", "html", "csv", "pages", "eval"):
        assert audit.files[key].exists(), key


def test_findings_json_roundtrip(audit):
    data = json.loads(audit.files["json"].read_text())
    assert data["summary"]["findings"] == len(audit.findings)
    assert {"buy-phone", "pay-bill", "switch-plan"} == set(data["flows"])


def test_backlog_csv(audit):
    with audit.files["csv"].open() as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == BACKLOG_COLUMNS
    assert len(rows) == len(audit.findings)
    assert {r["action"] for r in rows} <= {"rename", "redesign", "add-component"}


def test_html_is_self_contained(audit):
    html = audit.files["html"].read_text()
    assert html.count("data:image/jpeg;base64,") >= 2 * len(audit.pairs)
    assert 'src="screenshots/' not in html and "<link" not in html
    assert "Running in offline demo mode" in html


def test_markdown_has_sections(audit):
    md = audit.files["md"].read_text()
    for heading in ("## Executive summary", "## Findings", "## Happy-path flows", "## Evaluation vs planted differences"):
        assert heading in md

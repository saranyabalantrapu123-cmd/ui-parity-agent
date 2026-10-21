"""Score findings against the ground truth in demo_sites/PLANTED_DIFFERENCES.yaml.

A finding matches a planted difference when the category is the same, it is on the same page
(web or app path) or flow, and - if the planted entry names a ``subject`` - the subjects agree
(fuzzy partial match >= 85 after normalisation). Matching is one-to-one.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from .models import Finding
from .textutil import norm

CATEGORIES = ("page_name", "chatbot", "component", "cta", "flow", "coverage")


@dataclass
class Score:
    category: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "precision": round(self.precision, 3), "recall": round(self.recall, 3)}


@dataclass
class EvalResult:
    per_category: list[Score]
    overall: Score
    matches: list[dict[str, str]] = field(default_factory=list)
    missed: list[dict[str, Any]] = field(default_factory=list)
    false_positives: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.to_dict(),
            "per_category": [s.to_dict() for s in self.per_category],
            "matches": self.matches,
            "missed": self.missed,
            "false_positives": self.false_positives,
        }

    def to_markdown(self) -> str:
        lines = ["| Category | Planted | Found | TP | Precision | Recall |", "|---|---:|---:|---:|---:|---:|"]
        for s in [*self.per_category, self.overall]:
            name = "**overall**" if s is self.overall else s.category
            lines.append(f"| {name} | {s.tp + s.fn} | {s.tp + s.fp} | {s.tp} | {s.precision:.2f} | {s.recall:.2f} |")
        return "\n".join(lines)


def load_planted(path: Path) -> list[dict[str, Any]]:
    return (yaml.safe_load(Path(path).read_text()) or {}).get("differences", [])


def _is_match(planted: dict[str, Any], f: Finding) -> bool:
    if planted["category"] != f.category:
        return False
    if "flow" in planted:
        if f.extra.get("flow_id") != planted["flow"]:
            return False
    else:
        same_page = (planted.get("web_page") and planted.get("web_page") == f.web_path) or (
            planted.get("app_page") and planted.get("app_page") == f.app_path
        )
        if not same_page:
            return False
    subject = planted.get("subject")
    return not subject or fuzz.partial_ratio(norm(subject), norm(f.subject)) >= 85


def evaluate(findings: list[Finding], planted_path: Path) -> EvalResult:
    planted = load_planted(planted_path)
    scores = {c: Score(c) for c in CATEGORIES}
    used: set[str] = set()
    matches, missed = [], []
    for p in planted:
        hit = next((f for f in findings if f.id not in used and _is_match(p, f)), None)
        scores.setdefault(p["category"], Score(p["category"]))
        if hit is None:
            scores[p["category"]].fn += 1
            missed.append(p)
        else:
            used.add(hit.id)
            scores[p["category"]].tp += 1
            matches.append({"planted": p["id"], "finding": hit.id, "category": p["category"]})
    false_positives = []
    for f in findings:
        if f.id not in used:
            scores.setdefault(f.category, Score(f.category))
            scores[f.category].fp += 1
            false_positives.append({"finding": f.id, "category": f.category, "page": f.page, "subject": f.subject})
    overall = Score(
        "overall",
        tp=sum(s.tp for s in scores.values()),
        fp=sum(s.fp for s in scores.values()),
        fn=sum(s.fn for s in scores.values()),
    )
    return EvalResult(list(scores.values()), overall, matches, missed, false_positives)


def evaluate_report(report_dir: Path, planted_path: Path) -> EvalResult:
    """Evaluate an existing report directory's findings.json."""
    data = json.loads((Path(report_dir) / "findings.json").read_text())
    return evaluate([Finding(**f) for f in data["findings"]], planted_path)

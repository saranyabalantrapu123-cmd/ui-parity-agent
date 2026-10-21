"""Paths and browser profiles."""
from __future__ import annotations

from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
DEMO_SITES_DIR = PROJECT_DIR / "demo_sites"
PLANTED_DIFFERENCES = DEMO_SITES_DIR / "PLANTED_DIFFERENCES.yaml"
DEFAULT_FLOWS = PROJECT_DIR / "flows.yaml"
REPORTS_DIR = PROJECT_DIR / "reports"
EXTRACT_JS = (PACKAGE_DIR / "js" / "extract.js").read_text()

# Desktop browser for the website.
WEB_CONTEXT: dict[str, Any] = {
    "viewport": {"width": 1366, "height": 900},
    "device_scale_factor": 1,
}

# iPhone-like emulation for the app. Mirrors Playwright's "iPhone 13" descriptor but runs on
# Chromium (the only browser installed) and uses a 2x scale factor to keep screenshots small.
APP_CONTEXT: dict[str, Any] = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 2,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
}


def context_options(platform: str) -> dict[str, Any]:
    return dict(APP_CONTEXT if platform == "app" else WEB_CONTEXT)

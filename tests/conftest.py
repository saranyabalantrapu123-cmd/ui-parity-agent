"""Shared fixtures. Everything runs offline: demo sites are served locally and the LLM is mocked."""
from __future__ import annotations

import os

import pytest

os.environ["LLM_MODEL"] = "mock"  # never call a real model from tests

from parity_agent.crawler import browser_session  # noqa: E402
from parity_agent.llm import MockLLM  # noqa: E402
from parity_agent.pipeline import AuditResult, run_audit  # noqa: E402


@pytest.fixture(scope="session")
def browser():
    """One Chromium for the whole session (Playwright's sync API allows one driver per thread)."""
    with browser_session() as b:
        yield b


@pytest.fixture(scope="session")
def audit(tmp_path_factory: pytest.TempPathFactory, browser) -> AuditResult:
    """One full end-to-end demo audit shared by all integration tests (~10s)."""
    return run_audit(out_root=tmp_path_factory.mktemp("reports"), llm=MockLLM(), browser=browser)

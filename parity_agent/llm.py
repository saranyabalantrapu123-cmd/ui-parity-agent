"""Shared LLM access via LiteLLM, with a deterministic offline MockLLM.

Every LLM call in this project goes through :func:`get_llm` and ``complete_json``. Callers pass a
rule-based ``mock`` function alongside the prompt; in offline mode (``LLM_MODEL=mock`` or no API key)
that function produces the answer, so the whole pipeline runs with no key and no network.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MODEL = "anthropic/claude-sonnet-4-5"
MOCK_BANNER = "Running in offline demo mode (no LLM key) — outputs are rule-based"

MockFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseLLM:
    is_mock: bool = False
    model: str = ""

    def __init__(self) -> None:
        self.usage = Usage()

    def complete_json(
        self, task: str, system: str, prompt: str, payload: dict[str, Any], mock: MockFn
    ) -> dict[str, Any]:
        raise NotImplementedError

    def describe(self) -> str:
        return MOCK_BANNER if self.is_mock else f"LLM: {self.model}"


class MockLLM(BaseLLM):
    """Deterministic stand-in: delegates to the caller's rule-based ``mock`` function."""

    is_mock = True
    model = "mock"

    def complete_json(
        self, task: str, system: str, prompt: str, payload: dict[str, Any], mock: MockFn
    ) -> dict[str, Any]:
        self.usage.calls += 1
        return mock(payload)


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object in a model reply (tolerates ```json fences and preambles)."""
    match = _JSON_BLOCK.search(text or "")
    if not match:
        raise ValueError(f"No JSON object in model output: {text[:200]!r}")
    return json.loads(match.group(0))


class LiteLLMClient(BaseLLM):
    """Real model through LiteLLM. Falls back to the rule-based answer if a call fails."""

    def __init__(self, model: str) -> None:
        super().__init__()
        self.model = model

    def complete_json(
        self, task: str, system: str, prompt: str, payload: dict[str, Any], mock: MockFn
    ) -> dict[str, Any]:
        import litellm  # imported lazily so offline runs never pay the import cost

        messages = [
            {"role": "system", "content": system + "\nRespond with a single JSON object and nothing else."},
            {"role": "user", "content": f"{prompt}\n\nInput JSON:\n{json.dumps(payload, indent=2)}"},
        ]
        try:
            response = litellm.completion(model=self.model, messages=messages, temperature=0, max_tokens=2000)
        except Exception as exc:
            log.warning("LLM call for %s failed (%s); using rule-based fallback", task, exc)
            return mock(payload)
        self.usage.calls += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.usage.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            self.usage.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
        try:
            self.usage.cost_usd += float(litellm.completion_cost(completion_response=response) or 0.0)
        except Exception:  # cost tables do not cover every model; tokens are still tracked
            log.debug("No cost data for %s", self.model)
        try:
            return parse_json_object(response.choices[0].message.content)
        except (ValueError, json.JSONDecodeError) as exc:
            log.warning("Unparseable LLM output for %s (%s); using rule-based fallback", task, exc)
            return mock(payload)


def _has_key(model: str) -> bool:
    if model.startswith("openai/") or model.startswith("gpt"):
        return bool(os.getenv("OPENAI_API_KEY"))
    if model.startswith("anthropic/") or model.startswith("claude"):
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))


def get_llm() -> BaseLLM:
    """Return the configured LLM, or MockLLM when ``LLM_MODEL=mock`` or no API key is present."""
    model = os.getenv("LLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if model == "mock" or not _has_key(model):
        return MockLLM()
    return LiteLLMClient(model)

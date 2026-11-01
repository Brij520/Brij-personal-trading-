"""Provider-independent LLM access with a deterministic fallback.

Design rules:

* The platform must work with **no** LLM credentials. Agents therefore carry a
  deterministic rule engine that produces structured findings on its own.
* When a provider is configured, it is used only to *phrase* findings and to
  run the bull/bear debate prose. It is never allowed to invent numbers: the
  prompt receives a frozen snapshot of computed metrics and is instructed to
  reference only those.
* Outputs are always validated against the pydantic schema; invalid output is
  discarded and the deterministic text is used instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from backend.core.config import Settings, get_settings
from backend.core.logging import get_logger

log = get_logger("llm")


class LLMUnavailable(RuntimeError):
    pass


class LLMClient(Protocol):
    name: str

    def available(self) -> bool: ...

    def complete(
        self, *, system: str, prompt: str, max_tokens: int = 900, temperature: float = 0.2
    ) -> str: ...


@dataclass
class DisabledLLM:
    """Used when no provider is configured (the default)."""

    name: str = "disabled"

    def available(self) -> bool:
        return False

    def complete(
        self, *, system: str, prompt: str, max_tokens: int = 900, temperature: float = 0.2
    ) -> str:
        raise LLMUnavailable(
            "No LLM provider configured. Deterministic rule engine output is used."
        )


@dataclass
class HTTPLLM:
    """Minimal OpenAI-compatible chat client (also works with Ollama / vLLM).

    Kept deliberately small: no SDK dependency, no retries beyond one, tight
    timeout. Any failure downgrades to the deterministic text rather than
    breaking the research run.
    """

    provider: str
    api_key: str | None
    model: str
    base_url: str
    timeout: float = 20.0

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}"

    def available(self) -> bool:
        return bool(self.api_key) or self.provider == "ollama"

    def complete(
        self, *, system: str, prompt: str, max_tokens: int = 900, temperature: float = 0.2
    ) -> str:
        if not self.available():
            raise LLMUnavailable(f"provider {self.provider} has no credentials")
        import httpx

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.base_url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            return str(data["choices"][0]["message"]["content"]).strip()
        except Exception as exc:  # noqa: BLE001 - degrade, never crash research
            raise LLMUnavailable(str(exc)) from exc


DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "ollama": "http://localhost:11434/v1/chat/completions",
}


def build_llm(settings: Settings | None = None) -> LLMClient:
    settings = settings or get_settings()
    if settings.llm_provider == "none" or not settings.llm_api_key:
        if settings.llm_provider == "ollama":
            pass
        else:
            return DisabledLLM()
    model = settings.llm_model or {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-sonnet-latest",
        "gemini": "gemini-1.5-flash",
        "ollama": "llama3.1",
    }.get(settings.llm_provider, "gpt-4o-mini")
    return HTTPLLM(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        model=model,
        base_url=settings.llm_base_url
        or DEFAULT_BASE_URLS.get(settings.llm_provider, DEFAULT_BASE_URLS["openai"]),
    )


RESEARCH_SYSTEM_PROMPT = (
    "You are an analyst inside a personal Indian equity research platform. "
    "Use ONLY the numbered metrics supplied. Never invent a number, a date, a "
    "source or a company fact that is not present in the input. If evidence is "
    "missing, say so explicitly. No profit promises, no price targets framed as "
    "certainties, no buy/sell advice. Write in plain professional English, "
    "maximum 120 words, and finish with the single largest risk to the thesis."
)


def narrate(llm: LLMClient, prompt: str, fallback: str) -> dict[str, Any]:
    """Try to narrate with the configured LLM, else use deterministic text."""
    if not llm.available():
        return {"text": fallback, "generated_by": "deterministic-rule-engine"}
    try:
        text = llm.complete(system=RESEARCH_SYSTEM_PROMPT, prompt=prompt)
    except LLMUnavailable as exc:
        log.warning("llm unavailable: %s", exc)
        return {"text": fallback, "generated_by": "deterministic-rule-engine"}
    if not text or len(text) < 20:
        return {"text": fallback, "generated_by": "deterministic-rule-engine"}
    return {"text": text, "generated_by": llm.name}

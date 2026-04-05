"""Gemini reasoning layer — the agent's primary judge.

Evaluates browser tabs AND desktop processes against the user's focus goal.
Rules (explicit /block and /allow) run first as a fast floor, but for
anything ambiguous Gemini is the decider: it returns BLOCK or ALLOW.

Decisions are cached per-key so we don't re-classify the same tab/process
every tick. Cache is cleared when the session resets.

Supports two auth paths:
  1. Service-account JSON in configs/ → Vertex AI (google-genai SDK)
  2. GEMINI_API_KEY / GOOGLE_API_KEY env var → Gemini API (google-generativeai)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.policy import Action, Decision


_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_TAB_PROMPT_PATH = _PROMPTS_DIR / "classify_tab.txt"
_PROCESS_PROMPT_PATH = _PROMPTS_DIR / "classify_process.txt"


class AI:
    """Thin wrapper around Gemini for tab classification."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "gemini-2.5-flash",
        service_account_path: Path | None = None,
        location: str = "us-central1",
    ) -> None:
        self._enabled = False
        self._backend = None  # "vertex" | "genai"
        self._client = None
        self._model_name = model
        self._tab_prompt = ""
        self._process_prompt = ""
        self._last_error: str = ""
        self._error_count: int = 0
        # Cache: key -> Decision. Avoids re-classifying the same tab/process each tick.
        self._cache: dict[str, Decision] = {}
        try:
            self._tab_prompt = _TAB_PROMPT_PATH.read_text(encoding="utf-8")
            self._process_prompt = _PROCESS_PROMPT_PATH.read_text(encoding="utf-8")
        except Exception:
            return

        # Prefer service account (Vertex AI) if provided.
        if service_account_path and service_account_path.exists():
            try:
                self._init_vertex(service_account_path, location)
                return
            except Exception as e:
                self._last_error = f"vertex init: {type(e).__name__}: {e}"

        # Fallback: plain API key via google-generativeai.
        if api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                self._client = genai.GenerativeModel(model)
                self._backend = "genai"
                self._enabled = True
            except Exception as e:
                self._last_error = f"genai init: {type(e).__name__}: {e}"
                self._enabled = False

    def _init_vertex(self, sa_path: Path, location: str) -> None:
        """Initialize the google-genai client against Vertex AI."""
        import os
        sa_data = json.loads(sa_path.read_text(encoding="utf-8"))
        project_id = sa_data.get("project_id")
        if not project_id:
            raise RuntimeError("service account missing project_id")
        # google-auth reads this env var to pick up the service account.
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(sa_path)
        from google import genai  # google-genai
        self._client = genai.Client(vertexai=True, project=project_id, location=location)
        self._backend = "vertex"
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def backend(self) -> str:
        return self._backend or "none"

    @property
    def model_name(self) -> str:
        return self._model_name

    def status_line(self) -> str:
        if not self._enabled:
            return f"AI disabled ({self._last_error or 'no credentials'})"
        return f"AI ready: {self._backend}/{self._model_name}"

    def reset_cache(self) -> None:
        """Clear classification cache + reset circuit breaker — call on session start."""
        self._cache.clear()
        self._error_count = 0
        self._last_error = ""

    def classify_tab(self, context, goal: str, recent_activity: list[str] | None = None) -> Decision:
        """Return a Decision. Always returns ALLOW on any failure."""
        if not self._enabled:
            return Decision(Action.ALLOW, "ai disabled", 0.0)
        if self._error_count >= 3:
            return Decision(Action.ALLOW, "ai circuit-broken", 0.0)
        # Cache by URL — same URL gets same verdict within the session.
        cache_key = f"tab::{context.url}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        prompt = (
            self._tab_prompt
            .replace("{{goal}}", goal or "")
            .replace("{{page_title}}", context.title or "")
            .replace("{{url}}", context.url or "")
            .replace("{{recent_activity}}", ", ".join(recent_activity or []))
        )
        decision = self._call_and_parse(prompt)
        # Don't cache transient failures — let the next tick retry.
        if "rate-limited" not in decision.reason and "ai error" not in decision.reason:
            self._cache[cache_key] = decision
        return decision

    def classify_process(self, process_name: str, goal: str) -> Decision:
        """Return a Decision for a running process. Cached by process name."""
        if not self._enabled:
            return Decision(Action.ALLOW, "ai disabled", 0.0)
        if self._error_count >= 3:
            return Decision(Action.ALLOW, "ai circuit-broken", 0.0)
        cache_key = f"proc::{process_name}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        prompt = (
            self._process_prompt
            .replace("{{goal}}", goal or "")
            .replace("{{process_name}}", process_name or "")
        )
        decision = self._call_and_parse(prompt)
        if "rate-limited" not in decision.reason and "ai error" not in decision.reason:
            self._cache[cache_key] = decision
        return decision

    def focus_coach_review(
        self,
        goal: str,
        mode: str,
        duration_minutes: int,
        elapsed_minutes: float,
        offenses: int,
        blocked_domains: list[str],
        events_summary: str,
        is_final: bool = False,
    ) -> str:
        """Ask Gemini for a personalized focus coaching review. Returns plain text."""
        if not self._enabled:
            return ""
        prompt_path = _PROMPTS_DIR / "focus_coach.txt"
        try:
            template = prompt_path.read_text(encoding="utf-8")
        except Exception:
            return ""
        review_type = "final session review" if is_final else "mid-session check-in"
        domains_str = ", ".join(blocked_domains[:10]) if blocked_domains else "none"
        prompt = (
            template
            .replace("{{goal}}", goal or "")
            .replace("{{mode}}", mode or "")
            .replace("{{duration}}", str(int(duration_minutes)))
            .replace("{{elapsed}}", f"{elapsed_minutes:.0f}")
            .replace("{{offenses}}", str(offenses))
            .replace("{{blocked_domains}}", domains_str)
            .replace("{{events_summary}}", events_summary or "no events logged")
            .replace("{{review_type}}", review_type)
        )
        try:
            return self._generate(prompt).strip()
        except Exception as e:
            self._last_error = f"{type(e).__name__}: {e}"
            return ""

    def _call_and_parse(self, prompt: str) -> Decision:
        try:
            text = self._generate(prompt)
            data = _extract_json(text)
            verdict = (data.get("decision") or "ALLOW").upper()
            reason = data.get("short_reason") or "ai decision"
            confidence = float(data.get("confidence") or 0.0)
            if verdict == "BLOCK":
                return Decision(Action.BLOCK, f"AI: {reason}", confidence)
            if verdict == "WARN":
                return Decision(Action.WARN, f"AI: {reason}", confidence)
            return Decision(Action.ALLOW, f"AI: {reason}", confidence)
        except Exception as e:
            err_text = f"{type(e).__name__}: {e}"
            self._last_error = err_text
            # Rate limits are transient — don't trip the circuit breaker.
            if "429" in err_text or "RESOURCE_EXHAUSTED" in err_text:
                return Decision(Action.ALLOW, "ai rate-limited, retry next tick", 0.0)
            self._error_count += 1
            return Decision(Action.ALLOW, f"ai error: {err_text[:120]}", 0.0)

    def _generate(self, prompt: str) -> str:
        if self._backend == "vertex":
            resp = self._client.models.generate_content(model=self._model_name, contents=prompt)
            return (getattr(resp, "text", None) or "").strip()
        if self._backend == "genai":
            resp = self._client.generate_content(prompt)
            return (getattr(resp, "text", None) or "").strip()
        return ""


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response."""
    if not text:
        return {}
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}

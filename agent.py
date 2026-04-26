"""
PawPal+ Agentic AI Layer
Generates an optimized daily care plan using a plan -> validate -> refine loop.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import anthropic
from dotenv import load_dotenv

from pawpal_system import Owner, Scheduler

# ---------------------------------------------------------------------------
# Logging — explicit FileHandler so it works regardless of import order
# ---------------------------------------------------------------------------

_fh = logging.FileHandler("pawpal.log", encoding="utf-8")
_fh.setFormatter(
    logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
)
logger = logging.getLogger("pawpal_agent")
logger.setLevel(logging.INFO)
if not logger.handlers:      # avoid duplicate handlers on Streamlit reruns
    logger.addHandler(_fh)

# Load .env before any class instantiation
load_dotenv()


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PlanStep:
    """One step in an AI-generated care plan."""

    time: str
    action: str
    pet_name: str
    reasoning: str
    duration_minutes: int
    priority: str


@dataclass
class CarePlan:
    """Complete output of the agentic planning loop."""

    steps: list[PlanStep]
    confidence: float
    warnings: list[str]
    reasoning_summary: str
    generated_at: str
    iterations: int          # 0 = guard fired, 1 = clean, 2 = refined


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a professional pet care planning assistant. "
    "Your job is to create optimized, realistic daily care plans for pet owners. "
    "Always respond with valid JSON only — no markdown, no explanation outside the JSON."
)

_PLAN_SCHEMA = (
    '{\n'
    '  "steps": [\n'
    '    {\n'
    '      "time": "HH:MM",\n'
    '      "action": "what to do",\n'
    '      "pet_name": "pet name",\n'
    '      "reasoning": "why this time",\n'
    '      "duration_minutes": 15,\n'
    '      "priority": "high|medium|low"\n'
    '    }\n'
    '  ],\n'
    '  "confidence": 0.85,\n'
    '  "reasoning_summary": "overall explanation"\n'
    '}'
)


class PawPalAgent:
    """Agentic workflow: plan -> validate -> (optional) refine."""

    CONFIDENCE_THRESHOLD = 0.6

    def __init__(self, owner: Owner) -> None:
        """Bind agent to an owner. Raises ValueError if API key is missing."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Copy .env.example to .env and add your key."
            )
        self.owner = owner
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-haiku-4-5-20251001"
        logger.info("PawPalAgent initialized for owner: %s", owner.name)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_context(self, tasks: list) -> str:
        """Format a task list as a human-readable context string for prompts."""
        lines = [f"Tasks for today ({date.today()}):"]
        for t in tasks:
            lines.append(
                f"- {t.time} | {t.description} | Pet: {t.pet_name} "
                f"| Priority: {t.priority} | Duration: {t.duration_minutes}min "
                f"| Frequency: {t.frequency}"
            )
        context = "\n".join(lines)
        logger.info("Context built for %d task(s)", len(tasks))
        return context

    def _parse_json(self, text: str) -> Optional[dict]:
        """Try to parse JSON from model output, stripping markdown fences if present."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            # strip ```json ... ``` fences
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None

    def _call(self, user_prompt: str, max_tokens: int) -> str:
        """Make a single Claude API call and return the text response."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text

    def _plan(self, context: str) -> dict:
        """Call Claude to generate an initial care plan as JSON."""
        user_prompt = (
            f"Given these pet care tasks:\n\n{context}\n\n"
            f"Create an optimized daily care plan. "
            f"Return a JSON object with this exact schema:\n{_PLAN_SCHEMA}"
        )
        try:
            text = self._call(user_prompt, max_tokens=2000)
        except anthropic.APIError as e:
            logger.error("API error in _plan: %s", e)
            raise RuntimeError(f"Claude API error during planning: {e}") from e

        result = self._parse_json(text)
        if result is None:
            logger.warning("JSON parse failed on first attempt — retrying _plan")
            retry_prompt = user_prompt + "\n\nIMPORTANT: Respond with valid JSON only."
            try:
                text2 = self._call(retry_prompt, max_tokens=2000)
            except anthropic.APIError as e:
                logger.error("API error in _plan retry: %s", e)
                raise RuntimeError(f"Claude API error during planning retry: {e}") from e
            result = self._parse_json(text2)
            if result is None:
                logger.error("JSON parse failed on retry — returning fallback plan")
                return {
                    "steps": [],
                    "confidence": 0.0,
                    "reasoning_summary": "Plan generation failed — could not parse AI response.",
                }

        logger.info("_plan() complete — %d step(s) generated", len(result.get("steps", [])))
        return result

    def _validate(self, plan_json: dict, context: str) -> list[str]:
        """Ask Claude to check its own plan. Returns a list of issue strings (empty = valid)."""
        user_prompt = (
            f"Here is the original task list:\n\n{context}\n\n"
            f"Here is the care plan:\n\n{json.dumps(plan_json, indent=2)}\n\n"
            "Review this plan carefully. List any issues: missing high-priority tasks, "
            "time conflicts, or infeasible sequences. "
            "If the plan looks good, respond with exactly the word: VALID"
        )
        try:
            text = self._call(user_prompt, max_tokens=500)
        except anthropic.APIError as e:
            logger.warning("API error in _validate (non-fatal): %s", e)
            return []   # treat validation failure as "no issues"

        text = text.strip()
        if "VALID" in text.upper()[:30]:
            logger.info("_validate() found no issues")
            return []

        issues = [line.strip("- ").strip() for line in text.splitlines() if line.strip()]
        logger.warning("_validate() found %d issue(s): %s", len(issues), issues)
        return issues

    def _refine(self, plan_json: dict, context: str, issues: list[str]) -> dict:
        """Ask Claude to correct the plan given a list of issues."""
        issue_list = "\n".join(f"- {i}" for i in issues)
        user_prompt = (
            f"Here is the original task list:\n\n{context}\n\n"
            f"Here is the current care plan:\n\n{json.dumps(plan_json, indent=2)}\n\n"
            f"The following issues were found:\n{issue_list}\n\n"
            f"Please return a corrected care plan as JSON using the same schema:\n{_PLAN_SCHEMA}"
        )
        try:
            text = self._call(user_prompt, max_tokens=2000)
        except anthropic.APIError as e:
            logger.error("API error in _refine: %s", e)
            raise RuntimeError(f"Claude API error during refinement: {e}") from e

        result = self._parse_json(text)
        if result is None:
            logger.warning("JSON parse failed in _refine on first attempt — retrying")
            retry_prompt = user_prompt + "\n\nIMPORTANT: Respond with valid JSON only."
            try:
                text2 = self._call(retry_prompt, max_tokens=2000)
            except anthropic.APIError as e:
                logger.error("API error in _refine retry: %s", e)
                raise RuntimeError(f"Claude API error during refinement retry: {e}") from e
            result = self._parse_json(text2)
            if result is None:
                logger.error("JSON parse failed in _refine on retry — keeping original plan")
                return plan_json   # fall back to the unrefined plan

        logger.info("_refine() complete")
        return result

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def generate_plan(self, target_date: Optional[date] = None) -> CarePlan:
        """
        Run the full agentic loop and return a CarePlan.

        Steps: plan -> validate -> (optional, once) refine.
        Never raises; errors surface as warnings inside the returned CarePlan
        or as RuntimeError for API failures.
        """
        if target_date is None:
            target_date = date.today()

        tasks = Scheduler(self.owner).get_todays_schedule()

        # Guardrail: no tasks today
        if not tasks:
            logger.warning("Empty schedule guardrail triggered — no tasks for %s", target_date)
            return CarePlan(
                steps=[],
                confidence=0.0,
                warnings=["No tasks are scheduled for today. Add tasks first."],
                reasoning_summary="",
                generated_at=str(target_date),
                iterations=0,
            )

        context = self._build_context(tasks)

        plan_json = self._plan(context)
        issues = self._validate(plan_json, context)
        iterations = 1

        if issues:
            plan_json = self._refine(plan_json, context, issues)
            iterations = 2

        # Build PlanStep objects, normalising "description" -> "action" if needed
        raw_steps = plan_json.get("steps", [])
        steps: list[PlanStep] = []
        for s in raw_steps:
            # Claude occasionally uses "description" instead of "action"
            if "action" not in s and "description" in s:
                s = {**s, "action": s.pop("description")}
            try:
                steps.append(PlanStep(**s))
            except TypeError as e:
                logger.warning("Skipping malformed step %s: %s", s, e)

        confidence = float(plan_json.get("confidence", 0.0))
        reasoning_summary = plan_json.get("reasoning_summary", "")
        warnings: list[str] = []

        # Guardrail: low confidence
        if confidence < self.CONFIDENCE_THRESHOLD:
            msg = f"Low confidence score ({confidence:.2f}). Plan may need manual review."
            warnings.append(msg)
            logger.warning(msg)

        logger.info(
            "generate_plan() complete — %d step(s), confidence %.2f, iterations %d",
            len(steps), confidence, iterations,
        )
        return CarePlan(
            steps=steps,
            confidence=confidence,
            warnings=warnings,
            reasoning_summary=reasoning_summary,
            generated_at=str(target_date),
            iterations=iterations,
        )

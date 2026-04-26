"""
Tests for PawPalAgent — all mock-based, no real API calls required.
Run with: python -m pytest tests/test_agent.py -v
"""

import json
import os
from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest

from pawpal_system import Owner, Pet, Task


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def today():
    return date.today()


@pytest.fixture
def owner_with_tasks(today):
    """Owner with one dog and two tasks due today."""
    owner = Owner("Test Owner")
    pet = Pet("Buddy", "dog")
    pet.add_task(Task("Morning feeding", "07:00", 10, "high", "daily", "Buddy", today))
    pet.add_task(Task("Afternoon walk", "15:00", 30, "medium", "daily", "Buddy", today))
    owner.add_pet(pet)
    return owner


@pytest.fixture
def owner_no_tasks():
    """Owner with one pet but zero tasks."""
    owner = Owner("Empty Owner")
    owner.add_pet(Pet("Ghost", "cat"))
    return owner


# ---------------------------------------------------------------------------
# Helper: build a valid mock plan response dict
# ---------------------------------------------------------------------------

def _mock_plan_dict():
    return {
        "steps": [
            {
                "time": "07:00",
                "action": "Feed Buddy",
                "pet_name": "Buddy",
                "reasoning": "Morning routine — high priority.",
                "duration_minutes": 10,
                "priority": "high",
            },
            {
                "time": "15:00",
                "action": "Walk Buddy",
                "pet_name": "Buddy",
                "reasoning": "Afternoon exercise — medium priority.",
                "duration_minutes": 30,
                "priority": "medium",
            },
        ],
        "confidence": 0.9,
        "reasoning_summary": "Standard daily care: feed first, walk in the afternoon.",
    }


def _make_mock_response(content_text: str) -> MagicMock:
    """Create a MagicMock that mimics anthropic.Message with content[0].text."""
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=content_text)]
    return mock_resp


# ---------------------------------------------------------------------------
# Test 1: Empty schedule guard fires — no API call made
# ---------------------------------------------------------------------------

def test_empty_schedule_returns_warning(owner_no_tasks, monkeypatch):
    """When the owner has no tasks today, the guard returns a warning without calling Claude."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-000")

    with patch("agent.anthropic.Anthropic") as mock_anthropic_cls:
        from agent import PawPalAgent
        agent = PawPalAgent(owner_no_tasks)
        plan = agent.generate_plan()

    assert len(plan.warnings) > 0, "Expected a warning for empty schedule"
    assert plan.iterations == 0
    assert plan.steps == []
    # No API call should have been made
    mock_anthropic_cls.return_value.messages.create.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: Missing API key raises ValueError
# ---------------------------------------------------------------------------

def test_missing_api_key_raises_error(owner_with_tasks, monkeypatch):
    """PawPalAgent.__init__ must raise ValueError when ANTHROPIC_API_KEY is absent."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with patch("agent.anthropic.Anthropic"):
        from agent import PawPalAgent
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            PawPalAgent(owner_with_tasks)


# ---------------------------------------------------------------------------
# Test 3: Plan step count matches tasks
# ---------------------------------------------------------------------------

def test_plan_step_count_matches_tasks(owner_with_tasks, monkeypatch):
    """The returned CarePlan should have one step per task in the mocked response."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-111")

    plan_dict = _mock_plan_dict()
    mock_resp = _make_mock_response(json.dumps(plan_dict))

    with patch("agent.anthropic.Anthropic") as mock_anthropic_cls:
        mock_anthropic_cls.return_value.messages.create.return_value = mock_resp
        from agent import PawPalAgent
        agent = PawPalAgent(owner_with_tasks)
        # Mock _validate to return no issues so _refine is never called
        agent._validate = MagicMock(return_value=[])
        plan = agent.generate_plan()

    assert len(plan.steps) == 2
    assert plan.steps[0].action == "Feed Buddy"
    assert plan.steps[1].action == "Walk Buddy"


# ---------------------------------------------------------------------------
# Test 4: Low confidence adds a warning
# ---------------------------------------------------------------------------

def test_confidence_below_threshold_adds_warning(owner_with_tasks, monkeypatch):
    """A confidence score below 0.6 must add a warning to CarePlan.warnings."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-222")

    low_conf_dict = {**_mock_plan_dict(), "confidence": 0.4}
    mock_resp = _make_mock_response(json.dumps(low_conf_dict))

    with patch("agent.anthropic.Anthropic") as mock_anthropic_cls:
        mock_anthropic_cls.return_value.messages.create.return_value = mock_resp
        from agent import PawPalAgent
        agent = PawPalAgent(owner_with_tasks)
        agent._validate = MagicMock(return_value=[])
        plan = agent.generate_plan()

    assert len(plan.warnings) > 0
    assert any("confidence" in w.lower() or "0.4" in w for w in plan.warnings)
    assert plan.confidence == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Test 5: _validate issues trigger _refine (iterations == 2)
# ---------------------------------------------------------------------------

def test_validate_triggers_refine(owner_with_tasks, monkeypatch):
    """When _validate returns issues, _refine must be called once and iterations == 2."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-333")

    plan_dict = _mock_plan_dict()
    mock_resp = _make_mock_response(json.dumps(plan_dict))

    with patch("agent.anthropic.Anthropic") as mock_anthropic_cls:
        mock_anthropic_cls.return_value.messages.create.return_value = mock_resp
        from agent import PawPalAgent
        agent = PawPalAgent(owner_with_tasks)

        # _plan returns the good dict; _validate finds an issue; _refine returns corrected dict
        agent._plan = MagicMock(return_value=plan_dict)
        agent._validate = MagicMock(return_value=["Missing high-priority task: Luna's medication"])
        agent._refine = MagicMock(return_value=plan_dict)

        plan = agent.generate_plan()

    assert plan.iterations == 2, f"Expected iterations=2, got {plan.iterations}"
    agent._refine.assert_called_once()

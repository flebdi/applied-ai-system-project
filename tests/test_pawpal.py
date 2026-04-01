"""
Automated tests for PawPal+ core behaviors.
Run with: python -m pytest
"""

from datetime import date, timedelta

import pytest

from pawpal_system import Owner, Pet, Task, Scheduler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def today():
    return date.today()


@pytest.fixture
def owner():
    return Owner("Test Owner")


@pytest.fixture
def pet_with_tasks(today):
    pet = Pet(name="Buddy", species="dog")
    pet.add_task(Task("Evening walk", "18:00", 30, "medium", "daily", "Buddy", today))
    pet.add_task(Task("Morning feeding", "07:00", 10, "high", "daily", "Buddy", today))
    pet.add_task(Task("Midday treat", "12:00", 5, "low", "once", "Buddy", today))
    return pet


@pytest.fixture
def scheduler_with_pets(owner, pet_with_tasks):
    owner.add_pet(pet_with_tasks)
    return Scheduler(owner)


# ---------------------------------------------------------------------------
# Task tests
# ---------------------------------------------------------------------------

def test_mark_complete_changes_status():
    """Calling mark_complete() must flip completed from False to True."""
    task = Task("Walk", "08:00", 20, "high", "once", "Buddy")
    assert task.completed is False
    task.mark_complete()
    assert task.completed is True


def test_task_defaults_to_incomplete():
    task = Task("Feed", "07:00", 10, "high", "daily", "Kitty")
    assert task.completed is False


# ---------------------------------------------------------------------------
# Pet tests
# ---------------------------------------------------------------------------

def test_add_task_increases_count():
    """Adding a task to a Pet must increase its task count by 1."""
    pet = Pet("Rex", "dog")
    before = len(pet.get_tasks())
    pet.add_task(Task("Walk", "09:00", 20, "high", "once", "Rex"))
    assert len(pet.get_tasks()) == before + 1


def test_remove_task_decreases_count():
    pet = Pet("Rex", "dog")
    task = Task("Walk", "09:00", 20, "high", "once", "Rex")
    pet.add_task(task)
    removed = pet.remove_task(task.id)
    assert removed is True
    assert len(pet.get_tasks()) == 0


def test_remove_nonexistent_task_returns_false():
    pet = Pet("Rex", "dog")
    assert pet.remove_task("does-not-exist") is False


# ---------------------------------------------------------------------------
# Owner tests
# ---------------------------------------------------------------------------

def test_owner_get_all_tasks_aggregates_pets():
    owner = Owner("Jordan")
    pet1 = Pet("Mochi", "dog")
    pet2 = Pet("Luna", "cat")
    pet1.add_task(Task("Walk", "08:00", 20, "high", "once", "Mochi"))
    pet2.add_task(Task("Feed", "07:00", 5, "high", "daily", "Luna"))
    owner.add_pet(pet1)
    owner.add_pet(pet2)
    assert len(owner.get_all_tasks()) == 2


def test_owner_find_pet_case_insensitive():
    owner = Owner("Jordan")
    owner.add_pet(Pet("Mochi", "dog"))
    assert owner.find_pet("mochi") is not None
    assert owner.find_pet("MOCHI") is not None
    assert owner.find_pet("ghost") is None


# ---------------------------------------------------------------------------
# Scheduler — sorting
# ---------------------------------------------------------------------------

def test_sort_by_time_is_chronological(scheduler_with_pets):
    """Tasks returned by sort_by_time must be in ascending HH:MM order."""
    tasks = scheduler_with_pets.owner.get_all_tasks()
    sorted_tasks = scheduler_with_pets.sort_by_time(tasks)
    times = [t.time for t in sorted_tasks]
    assert times == sorted(times)


def test_get_todays_schedule_excludes_future(today):
    """Tasks with due_date != today must NOT appear in today's schedule."""
    owner = Owner("Jordan")
    pet = Pet("Mochi", "dog")
    pet.add_task(Task("Today walk", "09:00", 20, "high", "once", "Mochi", today))
    pet.add_task(Task("Tomorrow walk", "09:00", 20, "high", "once", "Mochi", today + timedelta(days=1)))
    owner.add_pet(pet)
    sched = Scheduler(owner)
    todays = sched.get_todays_schedule()
    assert len(todays) == 1
    assert todays[0].description == "Today walk"


# ---------------------------------------------------------------------------
# Scheduler — filtering
# ---------------------------------------------------------------------------

def test_filter_by_status_pending(scheduler_with_pets):
    all_tasks = scheduler_with_pets.owner.get_all_tasks()
    pending = scheduler_with_pets.filter_by_status(all_tasks, completed=False)
    assert all(not t.completed for t in pending)


def test_filter_by_pet_name(scheduler_with_pets):
    all_tasks = scheduler_with_pets.owner.get_all_tasks()
    buddy_tasks = scheduler_with_pets.filter_by_pet(all_tasks, "Buddy")
    assert all(t.pet_name == "Buddy" for t in buddy_tasks)


# ---------------------------------------------------------------------------
# Scheduler — conflict detection
# ---------------------------------------------------------------------------

def test_detect_conflicts_finds_same_time(today):
    """Two tasks at the exact same time for the same day must trigger a warning."""
    owner = Owner("Jordan")
    pet = Pet("Mochi", "dog")
    pet.add_task(Task("Walk", "08:00", 20, "high", "once", "Mochi", today))
    pet.add_task(Task("Feed", "08:00", 5, "high", "once", "Mochi", today))
    owner.add_pet(pet)
    sched = Scheduler(owner)
    warnings = sched.detect_conflicts()
    assert len(warnings) == 1
    assert "08:00" in warnings[0]


def test_detect_conflicts_no_conflict(today):
    """Tasks at different times must produce zero warnings."""
    owner = Owner("Jordan")
    pet = Pet("Mochi", "dog")
    pet.add_task(Task("Walk", "08:00", 20, "high", "once", "Mochi", today))
    pet.add_task(Task("Feed", "09:00", 5, "high", "once", "Mochi", today))
    owner.add_pet(pet)
    sched = Scheduler(owner)
    assert sched.detect_conflicts() == []


# ---------------------------------------------------------------------------
# Scheduler — recurring tasks
# ---------------------------------------------------------------------------

def test_daily_task_recurrence_creates_next_day(today):
    """Marking a daily task complete must create a new task for tomorrow."""
    owner = Owner("Jordan")
    pet = Pet("Mochi", "dog")
    task = Task("Morning feeding", "07:30", 10, "high", "daily", "Mochi", today)
    pet.add_task(task)
    owner.add_pet(pet)
    sched = Scheduler(owner)

    next_task = sched.mark_task_complete(task)

    assert next_task is not None
    assert next_task.due_date == today + timedelta(days=1)
    assert next_task.description == "Morning feeding"
    assert next_task.completed is False


def test_weekly_task_recurrence_creates_next_week(today):
    """Marking a weekly task complete must create a new task 7 days later."""
    owner = Owner("Jordan")
    pet = Pet("Mochi", "dog")
    task = Task("Grooming", "11:00", 45, "low", "weekly", "Mochi", today)
    pet.add_task(task)
    owner.add_pet(pet)
    sched = Scheduler(owner)

    next_task = sched.mark_task_complete(task)

    assert next_task is not None
    assert next_task.due_date == today + timedelta(weeks=1)


def test_once_task_no_recurrence(today):
    """Marking a 'once' task complete must NOT create a new task."""
    owner = Owner("Jordan")
    pet = Pet("Mochi", "dog")
    task = Task("Vet appointment", "10:00", 60, "high", "once", "Mochi", today)
    pet.add_task(task)
    owner.add_pet(pet)
    sched = Scheduler(owner)

    next_task = sched.mark_task_complete(task)

    assert next_task is None

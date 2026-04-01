"""
main.py — CLI demo script for PawPal+
Run with: python main.py
"""

from datetime import date, timedelta

from pawpal_system import Owner, Pet, Task, Scheduler


def main():
    # ── 1. Set up owner ──────────────────────────────────────────────
    owner = Owner("Jordan")

    # ── 2. Add pets ──────────────────────────────────────────────────
    mochi = Pet(name="Mochi", species="dog", breed="Shiba Inu")
    luna  = Pet(name="Luna",  species="cat", breed="Tabby")
    owner.add_pet(mochi)
    owner.add_pet(luna)

    today = date.today()

    # ── 3. Add tasks (intentionally out of order to test sorting) ────
    mochi.add_task(Task(
        description="Afternoon walk",
        time="15:00",
        duration_minutes=30,
        priority="medium",
        frequency="daily",
        pet_name="Mochi",
        due_date=today,
    ))
    mochi.add_task(Task(
        description="Morning feeding",
        time="07:30",
        duration_minutes=10,
        priority="high",
        frequency="daily",
        pet_name="Mochi",
        due_date=today,
    ))
    mochi.add_task(Task(
        description="Vet appointment",
        time="10:00",
        duration_minutes=60,
        priority="high",
        frequency="once",
        pet_name="Mochi",
        due_date=today,
    ))
    luna.add_task(Task(
        description="Morning feeding",
        time="07:30",       # ← same time as Mochi's feeding → triggers conflict warning
        duration_minutes=5,
        priority="high",
        frequency="daily",
        pet_name="Luna",
        due_date=today,
    ))
    luna.add_task(Task(
        description="Medication",
        time="09:00",
        duration_minutes=5,
        priority="high",
        frequency="daily",
        pet_name="Luna",
        due_date=today,
    ))

    # Add a task for tomorrow to confirm it does NOT appear in today's view
    mochi.add_task(Task(
        description="Weekly grooming",
        time="11:00",
        duration_minutes=45,
        priority="low",
        frequency="weekly",
        pet_name="Mochi",
        due_date=today + timedelta(days=7),
    ))

    # ── 4. Create scheduler and print today's schedule ───────────────
    scheduler = Scheduler(owner)
    scheduler.print_schedule()

    # ── 5. Demonstrate filtering ──────────────────────────────────────
    print("-- Pending tasks for Mochi -----------------------------")
    mochi_pending = scheduler.filter_by_pet(
        scheduler.filter_by_status(owner.get_all_tasks(), completed=False),
        "Mochi"
    )
    for t in scheduler.sort_by_time(mochi_pending):
        print(f"  {t}")
    print()

    # ── 6. Mark a recurring task complete → auto-schedule next ───────
    morning_feed = mochi.tasks[1]   # "Morning feeding"
    print(f"Marking '{morning_feed.description}' for {morning_feed.pet_name} as complete...")
    next_task = scheduler.mark_task_complete(morning_feed)
    if next_task:
        print(f"  -> Next occurrence created for {next_task.due_date}: {next_task.description}\n")

    # ── 7. Print updated schedule showing completion ──────────────────
    scheduler.print_schedule()


if __name__ == "__main__":
    main()

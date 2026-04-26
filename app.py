"""
PawPal+ Streamlit UI
Run with: streamlit run app.py
"""

import streamlit as st
from datetime import date

from pawpal_system import Owner, Pet, Task, Scheduler
from agent import PawPalAgent, CarePlan

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="wide")

st.title("🐾 PawPal+")
st.caption("Smart pet care management — track feedings, walks, meds, and more.")

# ---------------------------------------------------------------------------
# Session state — persist Owner across Streamlit reruns
# ---------------------------------------------------------------------------

if "owner" not in st.session_state:
    st.session_state.owner = None

# ---------------------------------------------------------------------------
# Sidebar — owner & pet setup
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Setup")

    owner_name = st.text_input("Owner name", value="Jordan")
    if st.button("Set / update owner"):
        if st.session_state.owner is None:
            st.session_state.owner = Owner(owner_name)
        else:
            st.session_state.owner.name = owner_name
        st.success(f"Owner set to {owner_name}")

    st.divider()

    st.subheader("Add a pet")
    pet_name_input = st.text_input("Pet name", key="new_pet_name")
    species_input = st.selectbox("Species", ["dog", "cat", "rabbit", "bird", "other"])
    breed_input = st.text_input("Breed (optional)", value="Unknown")

    if st.button("Add pet"):
        if st.session_state.owner is None:
            st.warning("Set the owner name first.")
        elif not pet_name_input.strip():
            st.warning("Enter a pet name.")
        elif st.session_state.owner.find_pet(pet_name_input.strip()):
            st.warning(f"{pet_name_input} is already registered.")
        else:
            new_pet = Pet(pet_name_input.strip(), species_input, breed_input or "Unknown")
            st.session_state.owner.add_pet(new_pet)
            st.success(f"{new_pet.name} added!")

    if st.session_state.owner and st.session_state.owner.pets:
        st.divider()
        st.subheader("Pets")
        for p in st.session_state.owner.pets:
            st.markdown(f"- **{p.name}** ({p.species}, {p.breed})")

# ---------------------------------------------------------------------------
# Main area — guard against no owner
# ---------------------------------------------------------------------------

if st.session_state.owner is None:
    st.info("Use the sidebar to set an owner name and add pets to get started.")
    st.stop()

owner: Owner = st.session_state.owner
scheduler = Scheduler(owner)

# ---------------------------------------------------------------------------
# Tab layout
# ---------------------------------------------------------------------------

tab_add, tab_schedule, tab_filter, tab_complete, tab_ai = st.tabs(
    ["Add Task", "Today's Schedule", "Filter & Sort", "Mark Complete", "AI Care Planner"]
)

# ── Tab 1: Add task ────────────────────────────────────────────────────────
with tab_add:
    st.subheader("Schedule a new task")

    if not owner.pets:
        st.warning("Add at least one pet in the sidebar first.")
    else:
        pet_names = [p.name for p in owner.pets]

        col1, col2 = st.columns(2)
        with col1:
            selected_pet = st.selectbox("Pet", pet_names, key="task_pet")
            task_desc = st.text_input("Task description", placeholder="e.g. Morning walk")
            task_time = st.time_input("Time", key="task_time")
        with col2:
            task_duration = st.number_input("Duration (minutes)", min_value=1, max_value=480, value=20)
            task_priority = st.selectbox("Priority", ["low", "medium", "high"], index=1)
            task_frequency = st.selectbox("Frequency", ["once", "daily", "weekly"])
            task_date = st.date_input("Due date", value=date.today())

        if st.button("Add task", key="btn_add_task"):
            if not task_desc.strip():
                st.warning("Enter a task description.")
            else:
                pet = owner.find_pet(selected_pet)
                time_str = task_time.strftime("%H:%M")
                new_task = Task(
                    description=task_desc.strip(),
                    time=time_str,
                    duration_minutes=int(task_duration),
                    priority=task_priority,
                    frequency=task_frequency,
                    pet_name=selected_pet,
                    due_date=task_date,
                )
                pet.add_task(new_task)
                st.success(f"Task '{new_task.description}' added for {selected_pet} at {time_str}.")

# ── Tab 2: Today's schedule ─────────────────────────────────────────────────
with tab_schedule:
    st.subheader(f"Today's Schedule — {date.today()}")

    todays_tasks = scheduler.get_todays_schedule()

    conflicts = scheduler.detect_conflicts(todays_tasks)
    for w in conflicts:
        st.warning(w)

    if not todays_tasks:
        st.info("No tasks scheduled for today. Add some in the 'Add Task' tab.")
    else:
        rows = []
        for t in todays_tasks:
            rows.append({
                "Status": "DONE" if t.completed else "TODO",
                "Time": t.time,
                "Task": t.description,
                "Pet": t.pet_name,
                "Duration (min)": t.duration_minutes,
                "Priority": t.priority,
                "Frequency": t.frequency,
                "ID": t.id,
            })
        st.table(rows)

    # Summary metrics
    if todays_tasks:
        total = len(todays_tasks)
        done = sum(1 for t in todays_tasks if t.completed)
        st.metric("Tasks today", total)
        col_a, col_b = st.columns(2)
        col_a.metric("Completed", done)
        col_b.metric("Remaining", total - done)

# ── Tab 3: Filter & Sort ────────────────────────────────────────────────────
with tab_filter:
    st.subheader("Filter & Sort Tasks")

    all_tasks = owner.get_all_tasks()

    col1, col2, col3 = st.columns(3)
    with col1:
        filter_pet = st.selectbox(
            "Filter by pet",
            ["All"] + [p.name for p in owner.pets],
            key="filter_pet",
        )
    with col2:
        filter_status = st.selectbox(
            "Filter by status",
            ["All", "Pending", "Completed"],
            key="filter_status",
        )
    with col3:
        sort_mode = st.selectbox(
            "Sort by",
            ["Time (chronological)", "Priority (high first)"],
            key="sort_mode",
        )

    filtered = all_tasks
    if filter_pet != "All":
        filtered = scheduler.filter_by_pet(filtered, filter_pet)
    if filter_status == "Pending":
        filtered = scheduler.filter_by_status(filtered, completed=False)
    elif filter_status == "Completed":
        filtered = scheduler.filter_by_status(filtered, completed=True)

    if sort_mode == "Time (chronological)":
        filtered = scheduler.sort_by_time(filtered)
    else:
        filtered = scheduler.sort_by_priority(filtered)

    if not filtered:
        st.info("No tasks match your filters.")
    else:
        rows = [
            {
                "Status": "DONE" if t.completed else "TODO",
                "Time": t.time,
                "Due Date": str(t.due_date),
                "Task": t.description,
                "Pet": t.pet_name,
                "Priority": t.priority,
                "Frequency": t.frequency,
                "ID": t.id,
            }
            for t in filtered
        ]
        st.table(rows)

# ── Tab 4: Mark Complete ────────────────────────────────────────────────────
with tab_complete:
    st.subheader("Mark a Task Complete")

    pending_tasks = scheduler.filter_by_status(owner.get_all_tasks(), completed=False)

    if not pending_tasks:
        st.success("All tasks are completed!")
    else:
        task_options = {
            f"{t.time} | {t.description} ({t.pet_name}) [{t.frequency}] — ID:{t.id}": t
            for t in scheduler.sort_by_time(pending_tasks)
        }
        selected_label = st.selectbox("Select task to complete", list(task_options.keys()))
        selected_task = task_options[selected_label]

        if st.button("Mark as complete"):
            next_task = scheduler.mark_task_complete(selected_task)
            st.success(f"'{selected_task.description}' marked complete!")
            if next_task:
                st.info(
                    f"Recurring task scheduled: '{next_task.description}' "
                    f"for {next_task.due_date} at {next_task.time}."
                )

# ── Tab 5: AI Care Planner ──────────────────────────────────────────────────
with tab_ai:
    st.subheader("AI-Generated Daily Care Plan")
    st.caption(
        "Uses Claude AI to create an optimized, self-validated care plan for today. "
        "Requires an ANTHROPIC_API_KEY in your .env file."
    )
    st.caption(
        ":warning: This plan is for organizational purposes only. "
        "Never use AI output as a substitute for professional veterinary advice."
    )

    todays_tasks_ai = scheduler.get_todays_schedule()

    if not todays_tasks_ai:
        st.info("No tasks scheduled for today. Add tasks in the 'Add Task' tab first.")
    else:
        if st.button("Generate AI Plan for Today", key="btn_ai_plan"):
            try:
                with st.spinner("Generating plan... (up to 3 AI steps: plan, validate, refine)"):
                    plan: CarePlan = PawPalAgent(owner).generate_plan()

                for w in plan.warnings:
                    st.warning(w)

                if plan.steps:
                    col_conf, col_iter = st.columns(2)
                    col_conf.metric("Confidence", f"{plan.confidence:.0%}")
                    col_iter.metric(
                        "Iterations",
                        plan.iterations,
                        help="1 = plan accepted on first try. 2 = plan was refined after self-check.",
                    )

                    st.info(plan.reasoning_summary)

                    st.table([
                        {
                            "Time": s.time,
                            "Action": s.action,
                            "Pet": s.pet_name,
                            "Duration (min)": s.duration_minutes,
                            "Priority": s.priority,
                            "Reasoning": s.reasoning,
                        }
                        for s in plan.steps
                    ])

                    st.caption(
                        f"Plan for {plan.generated_at} | "
                        f"{'Clean plan — accepted on first try' if plan.iterations == 1 else 'Refined once after self-validation'}"
                    )
                else:
                    st.warning("The AI returned an empty plan. Check your tasks and try again.")

            except ValueError as e:
                st.error(f"Configuration error: {e}")
            except RuntimeError as e:
                st.error(f"AI planning failed: {e}")

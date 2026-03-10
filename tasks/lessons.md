# Lessons

- When the repo workflow requires `tasks/todo.md` and `tasks/lessons.md`, create any missing task-tracking file before implementation so the work stays auditable.
- For long-running Streamlit batch jobs, do not rely on in-run placeholder updates as the primary UX; prefer session-state plus reruns so the page rehydrates from real storage state between items.

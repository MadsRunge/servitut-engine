# Lessons

- When the repo workflow requires `tasks/todo.md` and `tasks/lessons.md`, create any missing task-tracking file before implementation so the work stays auditable.
- For long-running Streamlit batch jobs, do not rely on in-run placeholder updates as the primary UX; prefer session-state plus reruns so the page rehydrates from real storage state between items.
- When a correction points out control-flow assumptions or N+1 access patterns, make the guard explicit in code and preload shared metadata instead of relying on framework semantics or per-item storage reads.
- When adding decorative Streamlit sidebar UI with custom HTML/CSS, isolate it with its own class scope and disable pointer interaction unless the element is meant to be clickable.
- In Streamlit, treat `unsafe_allow_html=True` as fragile: escape all dynamic values and prefer native Markdown/widgets for progress and detail views to avoid DOM/layout corruption across reruns and expanders.

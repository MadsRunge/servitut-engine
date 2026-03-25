# Lessons

- When the repo workflow requires `tasks/todo.md` and `tasks/lessons.md`, create any missing task-tracking file before implementation so the work stays auditable.
- For long-running Streamlit batch jobs, do not rely on in-run placeholder updates as the primary UX; prefer session-state plus reruns so the page rehydrates from real storage state between items.
- When a correction points out control-flow assumptions or N+1 access patterns, make the guard explicit in code and preload shared metadata instead of relying on framework semantics or per-item storage reads.
- When adding decorative Streamlit sidebar UI with custom HTML/CSS, isolate it with its own class scope and disable pointer interaction unless the element is meant to be clickable.
- In Streamlit, treat `unsafe_allow_html=True` as fragile: escape all dynamic values and prefer native Markdown/widgets for progress and detail views to avoid DOM/layout corruption across reruns and expanders.
- When a user asks for a distinct pre-processing step in the workflow, give it its own Streamlit page and navigation step instead of burying it inside an adjacent page.
- When feedback refers to the final deliverable, map it to the exact workflow stage before implementing; post-generation editing belongs after report generation, not inside review or generic feedback docs.
- In Streamlit background work, attaching ScriptRunContext to the thread is not enough if the worker still touches `st.session_state`; move cross-thread communication to queues or persisted job state and let the main script own all Streamlit state writes.

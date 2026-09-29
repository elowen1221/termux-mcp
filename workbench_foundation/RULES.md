# Workbench Rules

- Keep the workspace root clean.
- Put temporary experiments in the designated scratch area; do not scatter one-off helpers through project roots.
- Every persistent box must contain an up-to-date `README.md`.
- Put chronological/history-heavy detail in `LOG.md`; keep `README.md` focused on current truth.
- Read a box README before modifying that box.
- Preserve rollback points before risky structural changes.
- Do not commit local/private material unless its ownership explicitly permits it.
- When useful work changes a box's current state, update its README before leaving it.
- `HANDOFF.md` contains only unfinished/current work. Finished knowledge must be moved into the relevant box README or log.
- Before leaving unfinished work, write a compact handoff checkpoint: current goal, box, verified state, cautions, and next action.
- A checkpoint may append durable history to `LOG.md`, but it must not silently rewrite a box README. The AI must consciously update README when the project's current truth changes.

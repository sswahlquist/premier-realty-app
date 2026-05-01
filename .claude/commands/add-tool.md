Add a new AI tool page to the Premier Realty Flask app. Follow these steps exactly:

**Step 1 — Gather requirements**
Ask me these four questions (all at once, in a numbered list) and wait for my answers before writing any code:
1. What is the tool called? (e.g. "Rent Estimator")
2. What URL path should it use? (e.g. `/rent`)
3. What inputs does it need? (e.g. address, beds, baths)
4. What should Claude AI generate? (e.g. estimated rent range + comparable rentals)

**Step 2 — Implement the tool**
Once I've answered, make all of these changes:

- **app.py**: Add a GET route for the page and a POST `/api/<path>` route for the AI call, decorated with `@gate_json("<tool_name>")`. Add the tool label to `TOOL_LABELS`. Follow the exact same pattern as existing tools (e.g. `/listing` + `/api/listing`).

- **templates/<name>.html**: Create a new template that `{% extends "base.html" %}`. Match the existing style — dark hero section, gold accents, card layout for results. Use the same form + loading spinner + JS fetch pattern as `listing.html` or `leads.html`.

- **base.html**: Add the new tool link in both places:
  1. The desktop nav bottom row (between the existing `·` dividers)
  2. The mobile dropdown menu (`nav-mobile-menu` div)

**Step 3 — Test instructions**
Tell me exactly what to enter in the form to do a quick test run, using a real Greenville TX example.

**Coding standards to follow:**
- All colors use CSS vars `var(--navy)` / `var(--gold)` or `#1a2332` / `#c8a97e`
- AI calls use `AI_MODEL` constant (never hardcode the model string)
- Logging via `app.logger.info()` — no print statements
- New tool must respect the 5/day free limit via `gate_json`

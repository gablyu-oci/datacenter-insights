# Power Contract Announcements Table — Heuristic Review

**File analyzed:** `frontend/src/components/tabs/PowerTab.tsx`

## Anchored complaints (heuristic violations)

- **[Aesthetic & Minimalist Design / Consistency & Standards]** — Top-right filter bar at lines 909–918 is two raw, unstyled `<select>` elements (Company + Type) sitting outside the table while a richer per-column filter row exists at 965–991. The visual mismatch and duplication makes the page feel half-finished and forces the user to learn two filter paradigms for the same table.
- **[Aesthetic & Minimalist Design]** — Buyer name is rendered as a tinted background pill (lines 194–196, `${buyerColor}22` bg + saturated text) on every row. Color is used for identity, not status, so the chromatic noise competes with truly meaningful signals (energy type, capacity) and increases visual load without conveying new information.
- **[Recognition rather than Recall / Visibility of System Status]** — There is no dedicated "Source" column body cell; ATERIO vs SEC EDGAR provenance is stuffed into the Buyer cell as a second pill (lines 197–204) even though the header row at line 946 advertises a "Source" column. Users must visually parse two pills inside one cell to learn where a row came from, and the header promise is broken.
- **[Match Between System and Real World / Recognition rather than Recall]** — No "Seller" column in the header list (939–946); the counterparty is only revealed after the user clicks to expand a row. For a *contract* announcements table, hiding one of the two parties to the contract violates the user's mental model of "deal = buyer + seller".
- **[Visibility of System Status]** — The Status column (header at 945, sortable on `status`) renders as a grey "—" for every row because the backend never populates `status` on Aterio or EDGAR feeds (fallback at line 182). A column that is 100% empty signals broken data and erodes trust in the rest of the table.

## Additional issues spotted

- **[Consistency & Standards]** — Sort affordance is a tiny 10px `ChevronUp/Down` that appears *only on the active column*. Inactive sortable columns look identical to non-sortable Headline, so clickability is discovered by trial.
- **[Recognition rather than Recall]** — Header `<th>` cells switch `cursor: pointer` based on `field` but have no hover background, no underline, no `aria-sort`. Clickability is invisible until hover.
- **[Aesthetic & Minimalist Design / Flexibility & Efficiency]** — Three stacked filter zones (external dropdowns + label header + per-column filter strip) compete for attention before the user sees data — high density, low scannability.
- **[Visibility of System Status]** — Loading state is plain centered text; empty state doesn't disambiguate "no data" from "filtered out". No skeleton to preserve layout, so the page jumps on load.
- **[Flexibility & Efficiency / Accessibility]** — `overflowX: auto` + `whiteSpace: nowrap` means narrow viewports scroll the whole table sideways. Headers are not sticky; on long result sets users lose context. Bare `<th onClick>` without `<button>` / `aria-sort` blocks keyboard + screen-reader users.
- **[Consistency & Standards]** — Capacity column lacks unit alignment: header says "Capacity" (no "MW"), values are left-aligned like everything else, hampering magnitude comparison.
- **[Error Prevention]** — Capacity "between" comparator has no validation that `value <= value2` and no per-column clear affordance.

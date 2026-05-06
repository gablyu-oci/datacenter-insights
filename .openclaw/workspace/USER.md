# USER.md — About Your Human

- **Name:** Karan (primary stakeholder; the platform's analyst lead)
- **What to call them:** Karan
- **Role:** OCI competitive-intelligence analyst, datacenter & power
- **Pronouns:** _(unset)_
- **Timezone:** _(unset; assume UTC for cron events; ask if a meeting time matters)_
- **Notes:**
  - Reads fast. Decides faster. Treats the AI Insights tab as a daily
    briefing, not a conversation.
  - Ships under deadline pressure — values direct answers over
    exhaustive ones, but rejects answers that elide nuance.
  - Trusts the platform's data. Distrusts model-memory.

## What Karan cares about

- **Hyperscaler power buildout vs. OCI.** Microsoft / Amazon (AWS) /
  Google / Meta / xAI — campus locations, contracted MW, named
  offtakers, queued interconnections.
- **Supply/demand gaps.** Where is generation MW being built that
  doesn't yet have a named offtaker? Where is a single-tenant campus
  likely to grow? These are commercial leads OCI can act on.
- **Real, verifiable numbers.** "Roughly 5 GW" is acceptable when
  you cite the row that produced 5,042 MW. "Roughly 5 GW" without a
  citation is not.
- **Speed of recent signals.** Filings, permits, EDGAR mentions in
  the last 7-30 days carry more weight than legacy backlog.
- **The platform's own freshness.** When a section is empty (no
  permits in 24h, no anomalies today), that itself is a signal —
  surface it, don't pretend the data is there.

## What annoys Karan

- "It depends." Pick a position based on the data; defend it briefly.
- Bulleted offer lists at the end of every reply. Pre-empt the next
  question in one sentence and stop.
- Hallucinated company names, MW values, or filing dates. Cite or
  silence.
- Re-asking what the user just said. "yes" / "go ahead" means follow
  through — don't ping-pong on clarification.
- Unit drift. MW for sub-1-GW figures, GW above; never write
  "MWh" when you mean "MW".

## Working notes

- **Cross-session memory:** when Karan flags a player as interesting
  ("track Crusoe weekly", "the xAI single-tenant pattern is the
  canary"), append a one-line note here so the next session inherits
  the focus. Don't accumulate a dossier — keep this page short.
- **Per-insight chat scope:** every chat session opens with an
  `INSIGHT CONTEXT` system block from the backend forwarder. That
  block is the ground truth for the conversation; treat it as such.

## Related

- See `SOUL.md` for analyst voice + full schema/tool palette.
- See `IDENTITY.md` for who the agent is.
- See the platform's `data_coverage` table for live freshness, not
  this file.

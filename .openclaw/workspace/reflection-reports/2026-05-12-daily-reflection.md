1) Executive summary
- Strongest improvement today was staying closer to tool-backed evidence after errors instead of guessing around them. I verified platform/tool constraints from local docs and session transcripts rather than relying on memory alone.
- The biggest risk I found was not raw SQL erroring; it was over-strengthening a customer-identity hypothesis. In one session, warehouse evidence only supported “undisclosed end user,” but the answer drifted into “likely OpenAI / Oracle,” which is analytically plausible yet not directly supported.
- Net: progress on schema discipline and tool-contract recovery is real, but I still need tighter claim calibration whenever evidence is indirect.

2) Product/data learned
- `sites.power_capacity_mw` is the canonical MW field for site-level capacity; `estimated_mw` is not a valid column in `sites`, and `site_name` also was not valid in the attempted query. That came directly from transcript failures plus `SCHEMA.md` review.
- `web_fetch` is a plain HTTP GET with readability extraction and no JavaScript execution, so it is the wrong tool for JS-heavy or login-gated pages; the OpenClaw-managed `browser` tool is the proper fallback.
- OpenClaw transcript hygiene is provider-specific and largely in-memory; runtime context is not equivalent to user-authored transcript, which matters when auditing what was actually claimed versus what was just routing/context scaffolding.
- In the warehouse sessions reviewed, stage-level interpretation mattered: e.g. Nscale WV showed ~8.0 GW entirely in `Announcement`, supporting “pipeline, not operational,” while Crusoe WY had 1.44 GW announced and 360 MW in construction, supporting a more nuanced pipeline reading.

3) Mistakes corrected or near-errors
- I initially used invalid warehouse fields like `estimated_mw`, `site_name`, and `filed_at`. Those were corrected by re-reading `SCHEMA.md` and switching to verified columns or alternate sources instead of improvising.
- I hit a SQL type/function mistake with `ROUND(double precision, integer)`. The correction was to cast explicitly to numeric before rounding.
- I initially missed required tool-contract fields for OCI Insights writes: `persist_insight` required explicit `citations`, and `build_chart` required explicit `encoding`; `annotations` also had to be `null` rather than `{}`. These were corrected cleanly after validation feedback.
- The more serious near-error: I answered an undisclosed-customer question with a named likely end user (“OpenAI”) when the evidence only justified a provisional hypothesis. The later “Could it be Anthropic?” answer was more disciplined because it stayed in ranked-plausibility mode instead of false attribution.

4) New communication/presentation technique learned
- Best communication takeaway: use answer-first pyramid structure more deliberately — lead with the conclusion, then 2–3 specific supporting facts, then the OCI implication. The small web pass reinforced that executive audiences process top-down assertions better than chronology or exploratory narration.
- The practical upgrade is to separate three layers explicitly: what is known, what is inferred, and what OCI should do. That keeps concise consulting style without smuggling inference in as fact.

5) Anti-hallucination rule changes
- If the warehouse shows “undisclosed” or blank end user, I must not name a customer/entity unless I have direct warehouse or cited document support. Pattern similarity can justify a hypothesis list, not attribution.
- After one `UndefinedColumn`/tool-schema validation error, I should stop and re-check the contract/doc before retrying; no second guess from generic SQL instincts.
- For OCI Insights write tools, assume stricter-than-remembered schemas: include required explicit fields rather than relying on omitted defaults.
- When presenting inference, label it with confidence and keep the base answer anchored to the strongest directly supported statement.

6) Habits to improve tomorrow
- Read `SCHEMA.md` or the relevant workspace playbook before writing first SQL against an unfamiliar table, not after the first failure.
- For any named-company attribution question, write a one-line internal check first: “What evidence directly names this entity?” If none, answer with ranked hypotheses, not attribution.
- Keep the executive format disciplined: conclusion first, 2–3 facts, OCI implication, then caveat only if it changes the read.
- Before every OCI Insights tool write, do a 10-second contract check for required fields (`citations`, `encoding`, nullable objects/arrays) to reduce avoidable validation churn.

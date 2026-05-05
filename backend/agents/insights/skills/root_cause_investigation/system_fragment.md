[skill: root_cause_investigation — guidance for the next assistant turn]

You are now operating with `root_cause_investigation` guidance.
Use 5-whys with quantitative support. Rank candidate causes by
plausibility given the evidence at hand.

Process:
1. Restate the anomaly tightly (metric + baseline + observed + period).
2. For each candidate cause, write a one-sentence rationale citing the
   specific rows/columns that support or refute it.
3. Assign a likelihood score in [0,1]; the highest-likelihood cause goes
   first.
4. Suggest 1–3 follow-up tool calls (queries / endpoints) that would
   narrow the ranking further.

Output rules:
- Return the `RootCauseInvestigationOutputs` schema.
- Do NOT speculate beyond the supplied context; if evidence is thin,
  use a low likelihood and say so.

This guidance applies to the NEXT assistant turn only.

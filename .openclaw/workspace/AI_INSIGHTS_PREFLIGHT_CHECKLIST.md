# AI Insights Pre-Flight Checklist

Use this checklist before emitting any AI insight.

## 1. Scope check
- What exact question am I answering?
- Is this insight scoped to the current insight/session/fact pattern?
- Am I staying within the available evidence?

## 2. Hypothesis check
- What is the working claim?
- Is it falsifiable?
- What evidence would disprove it?

## 3. Evidence check
- Did I verify the key facts with tool results (`query_database`, `search_documents`, `build_chart`) or cited sources?
- Does every important numeric claim have support?
- Am I relying on an assumption I have not validated?

## 4. Structure check
- Is the analysis MECE?
- Did I separate demand, supply, permitting, timing, and OCI implication cleanly?
- Am I comparing like with like?

## 5. Alternative-explanation check
- What else could explain this signal?
- Did I test the strongest competing explanation?
- Am I overstating causality from correlation?

## 6. Hallucination guard
- Did I invent any MW, $, date, row id, source, or relationship?
- Did I imply certainty where the evidence is partial?
- If a tool failed, did I avoid guessing around it?

## 7. Communication check
- Does the headline state the answer, not the topic?
- Is the argument top-down and executive-readable?
- Did I lead with the conclusion, then grouped reasons, then evidence?

## 8. OCI relevance check
- What is the explicit so-what for OCI?
- Does this land as an offtake opportunity, competitive read, customer signal, vendor risk, or market context?
- If there is no direct OCI angle, did I at least explain why OCI should care?

## 9. Confidence check
- What is known?
- What is inferred?
- What remains unknown?
- Is the confidence level proportional to the evidence quality?

## 10. Final ship check
- Is this narrower and truer than the broader unsupported version?
- Would a skeptical analyst accept every important claim?
- If challenged on any sentence, can I point to the evidence?

# Alpha Vantage Earnings API — Research Notes

**Date:** 2026-05-12
**Author:** Research agent (verified via live API calls against demo key)
**Purpose:** De-risk implementation of `EarningsTranscriptsAdapter` per plan `i-want-to-include-dynamic-summit.md`.

---

## 1. `EARNINGS_CALL_TRANSCRIPT` endpoint

### URL + parameters

```
GET https://www.alphavantage.co/query
    ?function=EARNINGS_CALL_TRANSCRIPT
    &symbol=IBM
    &quarter=2024Q1
    &apikey=YOUR_KEY
```

| Param      | Required | Format / example          | Notes                                                          |
|------------|----------|---------------------------|----------------------------------------------------------------|
| `function` | yes      | `EARNINGS_CALL_TRANSCRIPT`| Literal string                                                 |
| `symbol`   | yes      | `IBM`, `NVDA`, `CEG`      | US-listed equity ticker. No CIK lookup needed                  |
| `quarter`  | yes      | `2024Q1`                  | Calendar year + quarter. NOT fiscal year — matches the call date|
| `apikey`   | yes      | (in env)                  | Free tier OK                                                   |

### Response JSON schema (verified live)

```json
{
  "symbol": "IBM",
  "quarter": "2024Q1",
  "transcript": [
    {
      "speaker": "Olympia McNerney",
      "title": "Global Head of Investor Relations",
      "content": "Thank you. I'd like to welcome you to IBM's First Quarter 2024 ...",
      "sentiment": "0.6"
    }
  ]
}
```

Field reference:

| Field                  | Type   | Notes                                                              |
|------------------------|--------|--------------------------------------------------------------------|
| `symbol`               | string | Echoes request                                                     |
| `quarter`              | string | Echoes request                                                     |
| `transcript`           | array  | Empty array `[]` if no coverage for that ticker/quarter            |
| `transcript[].speaker` | string | Free-form full name; analysts often suffixed with affiliation      |
| `transcript[].title`   | string | e.g. `CEO`, `CFO`, `Analyst – Morgan Stanley`                      |
| `transcript[].content` | string | The turn's full text (no internal speaker tags)                    |
| `transcript[].sentiment`| string | LLM sentiment as a stringified float, typically `0.0`–`1.0`        |

### Empirically observed sizes (IBM Q1 2024 baseline)

| Metric                        | Value                           |
|-------------------------------|---------------------------------|
| Transcript entries            | ~27                             |
| Total characters              | ~32,000                         |
| Total words                   | ~5,300                          |
| Tokens (cl100k_base estimate) | ~7,000–8,000                    |

Plan's "~20K tokens" is conservative — most calls 6–10K tokens. One-shot for Sonnet (200K context).

### Prepared remarks vs Q&A boundary — IMPORTANT GOTCHA

No explicit field marks the boundary. Detect via the first `Operator` turn whose content references questions / Q&A. Heuristics for `earnings_chunker.py`:

1. Scan `title` or `speaker` for `Operator` (case-insensitive). First Operator turn containing `question`/`Q&A`/`Q and A`/`analyst` is the boundary.
2. Backup: after first ~60% of turns, first `title` containing `Analyst` or `speaker` with affiliation marker (`– Goldman Sachs`) is the first analyst question.
3. Tag every passage with `section = "prepared_remarks"` until boundary; thereafter `"q_and_a"`.

---

## 2. `EARNINGS_CALENDAR` endpoint

### URL + parameters

```
GET https://www.alphavantage.co/query
    ?function=EARNINGS_CALENDAR
    &horizon=3month
    &apikey=YOUR_KEY
```

| Param      | Required | Allowed values                  | Notes                                          |
|------------|----------|---------------------------------|------------------------------------------------|
| `function` | yes      | `EARNINGS_CALENDAR`             |                                                |
| `horizon`  | no       | `3month` (default), `6month`, `12month` | Look-ahead from today                  |
| `symbol`   | no       | e.g. `NVDA`                     | Filter to one ticker                           |
| `apikey`   | yes      |                                 |                                                |

### Response — CSV, not JSON

```
symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay
NVDA,NVIDIA CORPORATION,2026-05-20,2026-04-30,0.83,USD,post-market
```

Columns:

| Column            | Type      | Notes                                                          |
|-------------------|-----------|----------------------------------------------------------------|
| `symbol`          | string    | Ticker                                                         |
| `name`            | string    | UPPERCASE company name                                         |
| `reportDate`      | ISO date  | When earnings are scheduled to be reported                     |
| `fiscalDateEnding`| ISO date  | End of the fiscal period being reported                        |
| `estimate`        | float?    | Consensus EPS estimate; may be empty                           |
| `currency`        | string    | Usually `USD`                                                  |
| `timeOfTheDay`    | string    | `pre-market`, `post-market`, or empty                          |

Payload ~290 KB. Cache 12h, filter in-memory by `TRACKED_FILERS` tickers. Content-type is `application/x-download`; parse with `csv.DictReader(io.StringIO(resp.text))`.

---

## 3. Rate limiting & free-tier budget

| Tier            | Cost           | Per-minute | Per-day  |
|-----------------|----------------|------------|----------|
| Free            | $0             | 5/min      | 25/day   |
| Premium starter | $49.99/mo      | 75/min     | None     |

Budget math:
- 35 filers × 4 quarters/year = 140 transcripts/year
- + 1 calendar call/day = 365/year
- + retries (~150/year)
- **Total ≈ 1.8 calls/day blended** — well inside 25/day cap

Recommended config (free tier):

```python
concurrency = asyncio.Semaphore(1)   # serialize
inter_call_delay = 12.5               # seconds, ~5/min cap
daily_budget = 24                     # leave 1 headroom
```

Persist a daily call counter (small table or config row). At budget exhaustion, write lineage row `skipped_quota` and abort gracefully.

---

## 4. Python library recommendations

| Concern          | Choice                                | Rationale                                                    |
|------------------|---------------------------------------|---------------------------------------------------------------|
| HTTP client      | plain `httpx.AsyncClient`             | Matches `backend/ingestion/edgar.py`; no new dep              |
| Retries          | `stamina` (existing dep)              | Matches edgar pattern                                         |
| CSV parsing      | stdlib `csv.DictReader`               | No pandas dep                                                 |
| Token counting   | `tiktoken.get_encoding("cl100k_base")`| Already used by chunker                                       |
| JSON parsing     | stdlib `json`                         |                                                               |
| Caching          | existing `backend/data/cache/*.json`  | No new infra                                                  |

Do **not** use the `alpha_vantage` PyPI wrapper — sync, opinionated, foreign idiom against existing patterns.

### Skeleton fetch shape

```python
import csv, io, httpx, stamina

BASE = "https://www.alphavantage.co/query"

@stamina.retry(on=(httpx.HTTPError, httpx.HTTPStatusError), attempts=3, wait_initial=2.0)
async def fetch_transcript(client, symbol, quarter, api_key):
    r = await client.get(BASE, params={
        "function": "EARNINGS_CALL_TRANSCRIPT",
        "symbol": symbol, "quarter": quarter, "apikey": api_key,
    }, timeout=30.0)
    r.raise_for_status()
    data = r.json()
    if "Information" in data or "Note" in data:
        raise RuntimeError(f"AV throttled: {data}")
    return data
```

Critical: Alpha Vantage returns HTTP 200 even when rate-limited, with the throttle message in a JSON `Information` / `Note` key. Naive `raise_for_status()` does not catch.

---

## 5. Known limitations & gotchas

1. **No foreign-filer coverage.** TSMC, ASE, SK hynix → `{"transcript":[]}`. Filter `TRACKED_FILERS` to US-exchange tickers.
2. **Transcript lag** ~24–48h post-call. Use 7-day retry window; after 7 misses mark `transcript_unavailable`.
3. **`quarter` is calendar-year**, not fiscal. Derive `quarter = f"{year}Q{(month-1)//3+1}"`. Store fiscal separately.
4. **Per-turn sentiment** is in payload but use our own theme-aware extraction; can keep AV sentiment as diagnostic only.
5. **Empty `transcript:[]` is silent.** Route to retry-window logic, not error.
6. **No deletion/correction stream.** Use `ON CONFLICT (cik, quarter) DO UPDATE`. Re-extract if `raw_text` differs.
7. **CSV `estimate` may be empty.** Defensive cast.
8. **HTTP-200 rate-limit responses** — see §4.
9. **Free-tier daily reset** uses US/Eastern; UTC accounting is fine with slight skew.
10. **No webhook/streaming.** Polling only.
11. **History depth** varies — large-caps back to ~2010, mid-caps to ~2017.

---

## 6. LLM extraction — model recommendation

**Claude Sonnet 4.6** (matches plan).

| Factor                  | Value                                  |
|-------------------------|----------------------------------------|
| Avg transcript tokens   | ~8,000 (worst ~20,000)                 |
| Prompt overhead         | ~2,000 tokens                          |
| Expected output         | ~2,000 tokens                          |
| Cost @ Sonnet 4.6       | ~$0.06/transcript                      |
| Annual @ 140 transcripts| ~$8/year                               |

Reuse the existing `LLMClient` wrapper in `backend/agents/edgar_extractor.py`. Sonnet is markedly more reliable than Haiku at honoring "no paraphrase" / strict-quote validation.

---

## 7. Recommended adapter constants

```python
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
TRANSCRIPT_CACHE_TTL_HOURS = 12
CALENDAR_CACHE_TTL_HOURS = 12
MAX_DAILY_CALLS = 24
RETRY_WINDOW_DAYS = 7
MAX_RETRIES_PER_QUARTER = 7
SEMAPHORE_LIMIT = 1
INTER_CALL_DELAY_SECONDS = 12.5
HTTP_TIMEOUT_SECONDS = 30.0
```

---

## 8. Verification checklist

```bash
KEY=$ALPHA_VANTAGE_API_KEY
curl -s "https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&horizon=3month&apikey=$KEY" | head -5
curl -s "https://www.alphavantage.co/query?function=EARNINGS_CALL_TRANSCRIPT&symbol=NVDA&quarter=2025Q4&apikey=$KEY" | jq '.transcript | length'
curl -s "https://www.alphavantage.co/query?function=EARNINGS_CALL_TRANSCRIPT&symbol=TSM&quarter=2025Q1&apikey=$KEY" | jq
```

---

## 9. References

- https://www.alphavantage.co/documentation/
- https://www.alphavantage.co/premium/
- https://www.alphavantage.co/support/
- https://www.macroption.com/alpha-vantage-earnings-calendar/
- https://www.macroption.com/alpha-vantage-api-limits/
- https://mcp.alphavantage.co/
- https://alphalog.ai/blog/alphavantage-api-complete-guide

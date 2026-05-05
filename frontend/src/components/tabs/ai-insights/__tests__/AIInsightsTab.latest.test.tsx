/**
 * AIInsightsTab — Phase 4 default-load tests.
 *
 * Vitest version installed: ^4.1.0 (clean resolve against vite ^8.0.9; no
 * fallback was needed). Test boundaries follow
 * docs/plans/ai-insights-automation/09-arch-phase4-followups.md §4 — we
 * mock `fetch` and rely on the EventSource stub from setupTests.ts.
 *
 * Closes the gaps in
 * docs/plans/ai-insights-automation/07-qa-test-plan-phase4.md §4:
 *   (a) default-load happy path renders the snapshot
 *   (b) Run-again must not flash an empty feed
 *   (c) Failed-latest banner + last_successful fallback
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  LatestInsight,
  LatestSessionResponseFull,
  LatestSessionRow,
} from "../../../../hooks/useLatestInsightSession";
import AIInsightsTab from "../AIInsightsTab";

// --------------------------- helpers ---------------------------

interface FetchRoute {
  /** Substring matched against the request URL. First match wins. */
  match: string;
  status?: number;
  body: unknown;
}

/**
 * Install a `fetch` stub that responds based on URL substring matching.
 * Routes are checked in order; the first whose `match` is a substring of
 * the URL is used. Unmatched URLs resolve with 404 + `{}` so feature-flag
 * health probes do not throw.
 */
function mockFetch(routes: FetchRoute[]): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    for (const route of routes) {
      if (url.includes(route.match)) {
        const status = route.status ?? 200;
        return {
          ok: status >= 200 && status < 300,
          status,
          json: async () => route.body,
        } as Response;
      }
    }
    return {
      ok: false,
      status: 404,
      json: async () => ({}),
    } as Response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function makeSession(overrides: Partial<LatestSessionRow> = {}): LatestSessionRow {
  return {
    id: "sess-1",
    status: "complete",
    started_at: "2026-05-04T09:00:00Z",
    ended_at: "2026-05-04T09:02:00Z",
    model: "test-model",
    focus: null,
    max_insights: 7,
    insights_emitted: 2,
    duration_ms: 120000,
    budget_status: "ok",
    created_by: "scheduler",
    cron_run_date: "2026-05-04",
    ...overrides,
  };
}

function makeInsight(overrides: Partial<LatestInsight> = {}): LatestInsight {
  return {
    id: "i1",
    session_id: "sess-1",
    idx: 0,
    headline: "Headline 1",
    body: null,
    confidence: "high",
    materiality: "M",
    skills_run: [],
    ...overrides,
  };
}

function makeLatestPayload(
  overrides: Partial<LatestSessionResponseFull> = {},
): LatestSessionResponseFull {
  return {
    session: makeSession(),
    insights: [
      makeInsight(),
      makeInsight({ id: "i2", idx: 1, headline: "Headline 2" }),
    ],
    is_today: true,
    generated_at: "2026-05-04T09:02:00Z",
    source: "scheduler",
    ...overrides,
  };
}

// --------------------------- tests ---------------------------

describe("AIInsightsTab — default-load Phase 4 behavior", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  // (a) default-load happy path
  it("renders the snapshot insights from /api/insights/latest", async () => {
    mockFetch([
      { match: "/api/insights/latest", body: makeLatestPayload() },
      { match: "/api/health", body: { ai_insights_v2: false } },
      { match: "/api/insights/health", body: { ai_insights_v2: false } },
    ]);

    render(<AIInsightsTab />);

    expect(await screen.findByText("Headline 1")).toBeInTheDocument();
    expect(screen.getByText("Headline 2")).toBeInTheDocument();
    // FailedLatestBanner is NOT rendered.
    expect(
      screen.queryByText(/Today's auto-run failed at/),
    ).not.toBeInTheDocument();
    // Run-again button is present.
    expect(
      screen.getByRole("button", { name: "Run again" }),
    ).toBeInTheDocument();
  });

  // (b) Run-again no-flash-of-empty
  it("keeps the snapshot visible across a Run-again click (no flash of empty)", async () => {
    mockFetch([
      { match: "/api/insights/latest", body: makeLatestPayload() },
      {
        match: "/api/insights/sessions",
        body: { session_id: "new-sess-id" },
      },
      { match: "/api/health", body: { ai_insights_v2: false } },
      { match: "/api/insights/health", body: { ai_insights_v2: false } },
    ]);

    render(<AIInsightsTab />);

    // Initial snapshot is on screen.
    expect(await screen.findByText("Headline 1")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Run again" }));

    // After the click the prior snapshot must still be rendered. We do
    // not drive the SSE stream — EventSource is a no-op stub from
    // setupTests.ts — so the parent tab is in the post-click /
    // pre-first-insight state.
    await waitFor(() => {
      expect(screen.getByText("Headline 1")).toBeInTheDocument();
    });
    expect(screen.getByText("Headline 2")).toBeInTheDocument();
  });

  // (c) Failed-latest with last_successful fallback
  it("renders FailedLatestBanner and the last_successful snapshot when latest is failed", async () => {
    const failedPayload: LatestSessionResponseFull = {
      session: makeSession({
        id: "sess-failed",
        status: "failed",
        started_at: "2026-05-05T09:05:00Z",
        ended_at: null,
        insights_emitted: 0,
        duration_ms: null,
        budget_status: null,
        cron_run_date: "2026-05-05",
      }),
      insights: [],
      is_today: true,
      generated_at: null,
      source: "scheduler",
      last_successful: {
        session: makeSession({
          id: "s-prev",
          status: "complete",
          started_at: "2026-05-04T09:00:00Z",
          ended_at: "2026-05-04T09:02:00Z",
          insights_emitted: 1,
          duration_ms: 120000,
          cron_run_date: "2026-05-04",
        }),
        insights: [
          makeInsight({
            id: "p1",
            session_id: "s-prev",
            idx: 0,
            headline: "Previous Headline",
          }),
        ],
      },
    };

    mockFetch([
      { match: "/api/insights/latest", body: failedPayload },
      { match: "/api/health", body: { ai_insights_v2: false } },
      { match: "/api/insights/health", body: { ai_insights_v2: false } },
    ]);

    render(<AIInsightsTab />);

    // The literal copy from FailedLatestBanner.tsx line 72.
    expect(
      await screen.findByText(/Today's auto-run failed at/),
    ).toBeInTheDocument();
    // last_successful snapshot is rendered below the banner.
    expect(screen.getByText("Previous Headline")).toBeInTheDocument();
    // Run-again button is still present.
    expect(
      screen.getByRole("button", { name: "Run again" }),
    ).toBeInTheDocument();
  });
});

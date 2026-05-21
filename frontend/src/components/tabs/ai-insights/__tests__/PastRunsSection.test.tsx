/**
 * PastRunsSection — Phase E tests.
 *
 * Covers, per docs/planning/save-and-history/00-PLAN.md §3 D3 and
 * 04-ux-design.md §2.2 / §2.3:
 *   1. First expand fires GET /api/insights/sessions and renders rows.
 *   2. Clicking a row fires GET /api/insights/sessions/{id}/insights and
 *      renders that session's InsightCards.
 *   3. Re-expand of the same row uses the per-row cache (no second fetch).
 *
 * Harness style mirrors AIInsightsTab.latest.test.tsx — substring URL
 * routing fetch stub, `vi.stubGlobal`, `userEvent.setup()`.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PastRunsSection from "../PastRunsSection";
import type { SessionHistoryRow } from "../../../../hooks/useSessionHistory";

// --------------------------- helpers ---------------------------

interface FetchRoute {
  match: string;
  status?: number;
  body: unknown;
}

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

function makeRow(overrides: Partial<SessionHistoryRow> = {}): SessionHistoryRow {
  return {
    id: "sess-xyz",
    status: "completed",
    started_at: "2026-05-04T09:00:00Z",
    finished_at: "2026-05-04T09:02:00Z",
    model: "test-model",
    focus: null,
    insights_emitted: 3,
    duration_ms: 120000,
    created_by: "scheduler",
    ...overrides,
  };
}

function sessionsPageBody(items: SessionHistoryRow[]) {
  return {
    items,
    total: items.length,
    limit: 20,
    offset: 0,
    has_more: false,
  };
}

// --------------------------- tests ---------------------------

describe("PastRunsSection", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("first expand triggers GET /api/insights/sessions and renders rows", async () => {
    const rows = [
      makeRow({ id: "sess-a", insights_emitted: 3, focus: "datacenter" }),
      makeRow({
        id: "sess-b",
        insights_emitted: 5,
        focus: "power",
        started_at: "2026-05-03T09:00:00Z",
      }),
    ];
    const fetchSpy = mockFetch([
      { match: "/api/insights/sessions", body: sessionsPageBody(rows) },
    ]);

    render(<PastRunsSection currentSessionId="sess-current" />);

    // Before expand, no /sessions fetch has fired.
    const sessionsCallsBefore = fetchSpy.mock.calls.filter(([u]) =>
      String(u).includes("/api/insights/sessions"),
    );
    expect(sessionsCallsBefore.length).toBe(0);

    // The Collapsible header is a button with aria-expanded=false.
    const header = screen.getByRole("button", { name: /Expand Past runs/i });
    expect(header).toHaveAttribute("aria-expanded", "false");

    const user = userEvent.setup();
    await user.click(header);

    // After expand, the fetch fires and rows render. Each row pill shows
    // its insights-emitted count.
    await waitFor(() => {
      expect(screen.getByText("3 insights")).toBeInTheDocument();
      expect(screen.getByText("5 insights")).toBeInTheDocument();
    });

    // The list endpoint matches "/api/insights/sessions?..." — distinguish
    // it from "/api/insights/sessions/{id}/insights" by checking the query
    // string. The list call uses `?limit=...`.
    const sessionsCalls = fetchSpy.mock.calls.filter(([u]) => {
      const s = String(u);
      return s.includes("/api/insights/sessions?") && !s.endsWith("/insights");
    });
    expect(sessionsCalls.length).toBeGreaterThanOrEqual(1);
  });

  it("clicking a row triggers /sessions/{id}/insights and renders InsightCards", async () => {
    const rows = [
      makeRow({ id: "sess-a", insights_emitted: 1, focus: "datacenter" }),
    ];
    const insightsBody = {
      items: [
        {
          id: "ins-past-a",
          session_id: "sess-a",
          idx: 0,
          headline: "Past headline A",
          confidence: "high",
          materiality: "M",
          skills_run: [],
          low_external_support: false,
          created_at: "2026-05-04T09:01:00Z",
          is_saved: false,
        },
      ],
      total: 1,
    };

    const fetchSpy = mockFetch([
      {
        match: "/api/insights/sessions/sess-a/insights",
        body: insightsBody,
      },
      {
        match: "/api/insights/sessions",
        body: sessionsPageBody(rows),
      },
    ]);

    render(<PastRunsSection currentSessionId="sess-current" />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Expand Past runs/i }));

    // Wait for the row to render.
    const rowButton = await screen.findByRole("button", {
      name: /Expand session from/i,
    });

    await user.click(rowButton);

    // The per-row /insights fetch fires and renders "Past headline A".
    expect(await screen.findByText("Past headline A")).toBeInTheDocument();

    const perRowCalls = fetchSpy.mock.calls.filter(([u]) =>
      String(u).includes("/api/insights/sessions/sess-a/insights"),
    );
    expect(perRowCalls.length).toBe(1);
  });

  it("re-expanding the same row uses the cache (no second fetch)", async () => {
    const rows = [
      makeRow({ id: "sess-a", insights_emitted: 1, focus: "datacenter" }),
    ];
    const insightsBody = {
      items: [
        {
          id: "ins-past-a",
          session_id: "sess-a",
          idx: 0,
          headline: "Past headline A",
          confidence: "high",
          materiality: "M",
          skills_run: [],
          low_external_support: false,
          created_at: "2026-05-04T09:01:00Z",
          is_saved: false,
        },
      ],
      total: 1,
    };

    const fetchSpy = mockFetch([
      {
        match: "/api/insights/sessions/sess-a/insights",
        body: insightsBody,
      },
      {
        match: "/api/insights/sessions",
        body: sessionsPageBody(rows),
      },
    ]);

    render(<PastRunsSection currentSessionId="sess-current" />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Expand Past runs/i }));

    const rowButton = await screen.findByRole("button", {
      name: /Expand session from/i,
    });

    // 1st expand: fires the per-row fetch.
    await user.click(rowButton);
    expect(await screen.findByText("Past headline A")).toBeInTheDocument();

    // Collapse the row.
    const collapseButton = await screen.findByRole("button", {
      name: /Collapse session from/i,
    });
    await user.click(collapseButton);
    await waitFor(() => {
      expect(screen.queryByText("Past headline A")).not.toBeInTheDocument();
    });

    // 2nd expand: hits cache, no new fetch.
    const reExpandButton = await screen.findByRole("button", {
      name: /Expand session from/i,
    });
    await user.click(reExpandButton);
    expect(await screen.findByText("Past headline A")).toBeInTheDocument();

    const perRowCalls = fetchSpy.mock.calls.filter(([u]) =>
      String(u).includes("/api/insights/sessions/sess-a/insights"),
    );
    expect(perRowCalls.length).toBe(1);

    // Sanity: a region renders the per-row insights body. There are two
    // regions in the DOM (the Collapsible outer region + the row's inner
    // region) — assert at least one of them contains "Past headline A".
    const regions = screen.getAllByRole("region");
    const headlineHost = regions.find((r) =>
      within(r).queryByText("Past headline A"),
    );
    expect(headlineHost).toBeTruthy();
  });
});

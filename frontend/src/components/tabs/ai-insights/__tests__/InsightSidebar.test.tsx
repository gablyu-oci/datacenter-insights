/**
 * InsightSidebar — mail-app layout tests.
 *
 * Mirrors the mocking style in AIInsightsTab.latest.test.tsx — substring
 * URL routing fetch stub via vi.stubGlobal. Covers:
 *
 *   1. Today group renders the supplied insights with rows.
 *   2. Clicking a Today row fires onSelect with the full insight object.
 *   3. First expand of Saved lazy-fetches /api/insights/saved (exactly once).
 *   4. First expand of Past runs lazy-fetches /api/insights/sessions and
 *      expanding a session row fetches /api/insights/sessions/{id}/insights;
 *      clicking a nested row fires onSelect with an adapted LatestInsight.
 *   5. Selected styling: aria-current="true" on the chosen row only.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import InsightSidebar from "../InsightSidebar";
import type { LatestInsight } from "../../../../hooks/useLatestInsightSession";

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
    low_external_support: false,
    created_at: "2026-05-13T09:00:00Z",
    chart: null,
    citations: [],
    is_saved: false,
    ...overrides,
  };
}

const noSaved = (_id: string, fallback: boolean): boolean => fallback;

// --------------------------- tests ---------------------------

describe("InsightSidebar", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the Today group expanded by default with N rows", async () => {
    mockFetch([]);
    const i1 = makeInsight();
    const i2 = makeInsight({ id: "i2", idx: 1, headline: "Headline 2" });

    render(
      <InsightSidebar
        todayInsights={[i1, i2]}
        selectedInsightId={null}
        effectiveSaved={noSaved}
        onSelect={() => undefined}
      />,
    );

    expect(screen.getByText("Headline 1")).toBeInTheDocument();
    expect(screen.getByText("Headline 2")).toBeInTheDocument();
  });

  it("fires onSelect with the full insight when a Today row is clicked", async () => {
    mockFetch([]);
    const i1 = makeInsight();
    const i2 = makeInsight({ id: "i2", idx: 1, headline: "Headline 2" });
    const onSelect = vi.fn();

    render(
      <InsightSidebar
        todayInsights={[i1, i2]}
        selectedInsightId={null}
        effectiveSaved={noSaved}
        onSelect={onSelect}
      />,
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: /Select insight: Headline 1/i }),
    );

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(i1);
  });

  it("lazy-loads /api/insights/saved on first Saved expand", async () => {
    const fetchSpy = mockFetch([
      {
        match: "/api/insights/saved",
        body: {
          items: [
            {
              id: "sv-a",
              session_id: "sess-old",
              idx: 0,
              headline: "Saved Alpha",
              body: null,
              confidence: "high",
              materiality: "M",
              skills_run: [],
              low_external_support: false,
              created_at: "2026-05-01T09:00:00Z",
              chart: null,
              citations: [],
              is_saved: true,
              saved_at: "2026-05-01T09:30:00Z",
            },
            {
              id: "sv-b",
              session_id: "sess-old",
              idx: 1,
              headline: "Saved Bravo",
              body: null,
              confidence: "medium",
              materiality: "M",
              skills_run: [],
              low_external_support: false,
              created_at: "2026-05-01T09:01:00Z",
              chart: null,
              citations: [],
              is_saved: true,
              saved_at: "2026-05-01T09:31:00Z",
            },
          ],
          total: 2,
          limit: 100,
        },
      },
    ]);

    render(
      <InsightSidebar
        todayInsights={[]}
        selectedInsightId={null}
        effectiveSaved={noSaved}
        onSelect={() => undefined}
      />,
    );

    // Before expand, no /saved fetch.
    const before = fetchSpy.mock.calls.filter(([u]) =>
      String(u).includes("/api/insights/saved"),
    );
    expect(before.length).toBe(0);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Expand Saved/i }));

    expect(await screen.findByText("Saved Alpha")).toBeInTheDocument();
    expect(screen.getByText("Saved Bravo")).toBeInTheDocument();

    const after = fetchSpy.mock.calls.filter(([u]) =>
      String(u).includes("/api/insights/saved"),
    );
    expect(after.length).toBe(1);
  });

  it("lazy-loads sessions on first Past runs expand and expands a session into nested insights", async () => {
    const sessionsBody = {
      items: [
        {
          id: "sess-past",
          status: "completed",
          started_at: "2026-05-10T09:00:00Z",
          finished_at: "2026-05-10T09:02:00Z",
          model: "test-model",
          focus: null,
          insights_emitted: 1,
          duration_ms: 120000,
          created_by: "scheduler",
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
      has_more: false,
    };
    const nestedBody = {
      items: [
        {
          id: "past-ins-1",
          session_id: "sess-past",
          idx: 0,
          headline: "Past Run Headline",
          confidence: "high",
          materiality: "M",
          skills_run: [],
          low_external_support: false,
          created_at: "2026-05-10T09:01:00Z",
          is_saved: false,
        },
      ],
      total: 1,
    };

    mockFetch([
      {
        match: "/api/insights/sessions/sess-past/insights",
        body: nestedBody,
      },
      { match: "/api/insights/sessions", body: sessionsBody },
    ]);

    const onSelect = vi.fn();
    render(
      <InsightSidebar
        todayInsights={[]}
        selectedInsightId={null}
        effectiveSaved={noSaved}
        onSelect={onSelect}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Expand Past runs/i }));

    // Session row appears.
    const sessionRowButton = await screen.findByRole("button", {
      name: /Expand session from/i,
    });

    await user.click(sessionRowButton);

    // Nested insight row renders.
    const nestedRow = await screen.findByRole("button", {
      name: /Select insight: Past Run Headline/i,
    });

    await user.click(nestedRow);

    // onSelect fires with adapted LatestInsight (body null, citations []).
    expect(onSelect).toHaveBeenCalledTimes(1);
    const arg = onSelect.mock.calls[0][0] as LatestInsight;
    expect(arg.id).toBe("past-ins-1");
    expect(arg.headline).toBe("Past Run Headline");
    expect(arg.body).toBeNull();
    expect(arg.citations).toEqual([]);
    expect(arg.session_id).toBe("sess-past");
  });

  it("applies aria-current=true to the selected row only", () => {
    mockFetch([]);
    const i1 = makeInsight();
    const i2 = makeInsight({ id: "i2", idx: 1, headline: "Headline 2" });

    render(
      <InsightSidebar
        todayInsights={[i1, i2]}
        selectedInsightId={i1.id}
        effectiveSaved={noSaved}
        onSelect={() => undefined}
      />,
    );

    const selectedRow = screen.getByRole("button", {
      name: /Select insight: Headline 1/i,
    });
    const otherRow = screen.getByRole("button", {
      name: /Select insight: Headline 2/i,
    });

    expect(selectedRow).toHaveAttribute("aria-current", "true");
    expect(otherRow).not.toHaveAttribute("aria-current");
  });
});

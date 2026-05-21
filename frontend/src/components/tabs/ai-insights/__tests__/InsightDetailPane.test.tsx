/**
 * InsightDetailPane — mail-app layout tests.
 *
 * Covers:
 *   1. Empty state when insight is null.
 *   2. Renders InsightCard headline + body when an insight is selected.
 *   3. Renders the saved variant of SubscribeButton when effectiveSaved
 *      returns true for the insight's id.
 *
 * Save-toggle bubbling through SubscribeButton hits the real /subscribe
 * endpoint via useInsightSubscription; we exercise the effectiveSaved path
 * (which controls SubscribeButton.initialSaved) as a pragmatic proxy and
 * leave the network-bubbling assertion as an it.todo.
 */

import { render, screen } from "@testing-library/react";
import InsightDetailPane from "../InsightDetailPane";
import type {
  LatestInsight,
  LatestSessionRow,
} from "../../../../hooks/useLatestInsightSession";

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

function makeSession(overrides: Partial<LatestSessionRow> = {}): LatestSessionRow {
  return {
    id: "sess-1",
    status: "complete",
    started_at: "2026-05-13T09:00:00Z",
    ended_at: "2026-05-13T09:02:00Z",
    model: "test-model",
    focus: null,
    max_insights: 5,
    insights_emitted: 1,
    duration_ms: 120000,
    budget_status: "ok",
    created_by: "scheduler",
    cron_run_date: "2026-05-13",
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
    low_external_support: false,
    created_at: "2026-05-13T09:01:00Z",
    chart: null,
    citations: [],
    is_saved: false,
    ...overrides,
  };
}

// --------------------------- tests ---------------------------

describe("InsightDetailPane", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the empty state when insight is null", () => {
    mockFetch([]);
    render(
      <InsightDetailPane
        insight={null}
        session={null}
        effectiveSaved={(_id, fb) => fb}
        onSaveToggle={() => undefined}
      />,
    );

    expect(
      screen.getByText("Pick an insight from the sidebar to read its detail."),
    ).toBeInTheDocument();
  });

  it("renders InsightCard headline + body when an insight is selected", () => {
    mockFetch([]);
    const insight = makeInsight({
      body: "The Wyoming buildout adds 1.5 GW",
      headline: "Wyoming buildout",
    });

    render(
      <InsightDetailPane
        insight={insight}
        session={makeSession()}
        total={1}
        effectiveSaved={(_id, fb) => fb}
        onSaveToggle={() => undefined}
      />,
    );

    // Headline appears inside the article aria-label "insight 1 of 1".
    expect(screen.getByText("Wyoming buildout")).toBeInTheDocument();
    expect(
      screen.getByText("The Wyoming buildout adds 1.5 GW"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("article", { name: /insight 1 of 1/i }),
    ).toBeInTheDocument();
  });

  it("renders the saved variant of SubscribeButton when effectiveSaved is true", () => {
    mockFetch([]);
    const insight = makeInsight({ id: "ins-saved", is_saved: false });

    render(
      <InsightDetailPane
        insight={insight}
        session={makeSession()}
        total={1}
        // Force effectiveSaved => true to verify the wiring threads through
        // to InsightCard.initialSaved => SubscribeButton's saved variant.
        effectiveSaved={() => true}
        onSaveToggle={() => undefined}
      />,
    );

    // SubscribeButton in the saved state exposes aria-label "Saved — click to remove".
    expect(
      screen.getByRole("button", { name: /Saved\s*[\u2014-].*click to remove/i }),
    ).toBeInTheDocument();
  });

  it.todo("save toggle bubbles to parent — covered indirectly via SubscribeButton.test.tsx");
});

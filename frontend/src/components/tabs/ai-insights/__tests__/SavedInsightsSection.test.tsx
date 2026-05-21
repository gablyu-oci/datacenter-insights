/**
 * SavedInsightsSection — Phase E tests.
 *
 * Covers, per docs/planning/save-and-history/00-PLAN.md §3 D4 and
 * 04-ux-design.md §2.4 / §2.5:
 *   1. Lazy load on expand: /api/insights/saved is NOT fetched until the
 *      Collapsible header is clicked; once expanded, both saved items
 *      render.
 *   2. Un-saving inside the section triggers DELETE /subscribe and a
 *      refetch of /saved — the un-saved row disappears, the fetch counter
 *      shows /saved was called twice.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SavedInsightsSection from "../SavedInsightsSection";
import type { SavedInsightRow } from "../../../../hooks/useSavedInsights";

// --------------------------- helpers ---------------------------

interface RouteHandler {
  match: string;
  method?: string;
  /** Function form so the test can swap behavior across calls. */
  handler: () => { status: number; body: unknown };
}

function mockFetchDynamic(handlers: RouteHandler[]): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    for (const h of handlers) {
      if (h.method && h.method.toUpperCase() !== method) continue;
      if (url.includes(h.match)) {
        const { status, body } = h.handler();
        return {
          ok: status >= 200 && status < 300,
          status,
          json: async () => body,
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

function makeSaved(overrides: Partial<SavedInsightRow> = {}): SavedInsightRow {
  return {
    id: "ins-a",
    session_id: "sess-1",
    idx: 0,
    headline: "Saved A",
    body: null,
    confidence: "high",
    materiality: "M",
    skills_run: [],
    low_external_support: false,
    created_at: "2026-05-04T09:01:00Z",
    chart: null,
    citations: [],
    is_saved: true,
    saved_at: "2026-05-04T09:05:00Z",
    ...overrides,
  };
}

// --------------------------- tests ---------------------------

describe("SavedInsightsSection", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("lazily loads /api/insights/saved on first expand and renders items", async () => {
    const itemsA = [
      makeSaved({ id: "ins-a", headline: "Saved A" }),
      makeSaved({ id: "ins-b", headline: "Saved B", idx: 1 }),
    ];

    const fetchSpy = mockFetchDynamic([
      {
        match: "/api/insights/saved",
        method: "GET",
        handler: () => ({
          status: 200,
          body: { items: itemsA, total: itemsA.length, limit: 100 },
        }),
      },
    ]);

    render(<SavedInsightsSection />);

    // Before expand, no /saved fetch.
    const savedCallsBefore = fetchSpy.mock.calls.filter(([u]) =>
      String(u).includes("/api/insights/saved"),
    );
    expect(savedCallsBefore.length).toBe(0);

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: /Expand Saved insights/i }),
    );

    expect(await screen.findByText("Saved A")).toBeInTheDocument();
    expect(screen.getByText("Saved B")).toBeInTheDocument();

    const savedCallsAfter = fetchSpy.mock.calls.filter(([u]) =>
      String(u).includes("/api/insights/saved"),
    );
    expect(savedCallsAfter.length).toBe(1);
  });

  it("un-saving inside the section refetches and removes the row", async () => {
    const initialItems = [
      makeSaved({ id: "ins-a", headline: "Saved A" }),
      makeSaved({ id: "ins-b", headline: "Saved B", idx: 1 }),
    ];
    const remainingItems = [
      makeSaved({ id: "ins-b", headline: "Saved B", idx: 1 }),
    ];

    let savedCallCount = 0;
    const fetchSpy = mockFetchDynamic([
      {
        match: "/api/insights/insights/ins-a/subscribe",
        method: "DELETE",
        handler: () => ({ status: 200, body: { ok: true } }),
      },
      {
        match: "/api/insights/saved",
        method: "GET",
        handler: () => {
          savedCallCount += 1;
          const body =
            savedCallCount === 1
              ? { items: initialItems, total: initialItems.length, limit: 100 }
              : {
                  items: remainingItems,
                  total: remainingItems.length,
                  limit: 100,
                };
          return { status: 200, body };
        },
      },
    ]);

    render(<SavedInsightsSection />);

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: /Expand Saved insights/i }),
    );

    expect(await screen.findByText("Saved A")).toBeInTheDocument();
    expect(screen.getByText("Saved B")).toBeInTheDocument();

    // The Saved toggle on each card has aria-label "Saved — click to remove".
    // We exclude the Collapsible header (aria-label "Collapse Saved insights")
    // by anchoring the regex on the start of the accessible name.
    const savedButtons = screen.getAllByRole("button", {
      name: /^Saved\b/i,
    });
    expect(savedButtons.length).toBe(2);

    await user.click(savedButtons[0]);

    // After the DELETE resolves and the section refetches, "Saved A" leaves
    // the DOM.
    await waitFor(() => {
      expect(screen.queryByText("Saved A")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Saved B")).toBeInTheDocument();

    const savedCalls = fetchSpy.mock.calls.filter(([u]) =>
      String(u).includes("/api/insights/saved"),
    );
    expect(savedCalls.length).toBe(2);
  });
});

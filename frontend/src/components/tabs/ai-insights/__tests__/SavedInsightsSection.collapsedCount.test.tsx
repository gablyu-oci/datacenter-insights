/**
 * SavedInsightsSection — collapsed-count behavior (Strategy-1).
 *
 * Per docs/planning/save-and-history-per-user/01-PRD.md §6 FR-6 and
 * §8.4: the collapsed header must NEVER show `(0)` while content exists.
 * It may show:
 *   - the real count, e.g. `(7)`, once /api/insights/counts resolves;
 *   - `(…)` while the counts request is in flight;
 *   - nothing at all if the request errored.
 *
 * These tests mount `SavedInsightsSection` in its default collapsed
 * state, mock the global `fetch` to drive each branch of the counts
 * lifecycle, and assert on the header text.
 */

import { render, screen, waitFor } from "@testing-library/react";
import SavedInsightsSection from "../SavedInsightsSection";

// --------------------------- helpers ---------------------------

interface CountsBody {
  saved: number;
  sessions: number;
}

function mockCountsFetch(
  options:
    | { kind: "ok"; body: CountsBody }
    | { kind: "error" }
    | { kind: "pending" },
): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();

    // /api/insights/counts — drive each branch.
    if (url.includes("/api/insights/counts")) {
      if (options.kind === "ok") {
        return {
          ok: true,
          status: 200,
          json: async () => options.body,
        } as Response;
      }
      if (options.kind === "error") {
        return Promise.reject(new Error("network down")) as unknown as Response;
      }
      // pending: never resolve.
      return new Promise<Response>(() => {
        /* hangs forever */
      });
    }

    // /api/insights/saved — section is collapsed in these tests, but
    // useSavedInsights might still get poked. Return an empty list to
    // keep the component branch-free; the assertions only care about
    // the collapsed header text, not the body.
    if (url.includes("/api/insights/saved")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ items: [], total: 0, limit: 100 }),
      } as Response;
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

function getCollapsedHeader(): HTMLElement {
  // Collapsed → aria-label "Expand Saved insights".
  return screen.getByRole("button", { name: /Expand Saved insights/i });
}

// --------------------------- tests ---------------------------

describe("SavedInsightsSection — collapsed-count Strategy-1", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the real count from /counts and never shows (0)", async () => {
    mockCountsFetch({ kind: "ok", body: { saved: 7, sessions: 12 } });

    render(<SavedInsightsSection />);

    await waitFor(() => {
      expect(getCollapsedHeader().textContent ?? "").toContain("(7)");
    });

    const text = getCollapsedHeader().textContent ?? "";
    expect(text).toContain("(7)");
    expect(text).not.toContain("(0)");
  });

  it("renders no count badge when /counts errors (never falls back to (0))", async () => {
    mockCountsFetch({ kind: "error" });

    render(<SavedInsightsSection />);

    // After the fetch rejects, the hook sets saved=null and Collapsible
    // hides the badge entirely. Wait for that steady state.
    await waitFor(() => {
      const text = getCollapsedHeader().textContent ?? "";
      // Pending marker must be gone (loading flipped back to false).
      expect(text).not.toContain("(…)");
    });

    const text = getCollapsedHeader().textContent ?? "";
    expect(text).not.toContain("(0)");
    // No numeric badge at all — match "(<digits>)".
    expect(text).not.toMatch(/\(\d+\)/);
  });

  it("shows (…) while /counts is still in flight (never (0))", async () => {
    mockCountsFetch({ kind: "pending" });

    render(<SavedInsightsSection />);

    // The pending marker `(…)` is set synchronously on the first render
    // after `useEffect` fires runFetch → setLoading(true).
    await waitFor(() => {
      const text = getCollapsedHeader().textContent ?? "";
      expect(text).toContain("(…)");
    });

    const text = getCollapsedHeader().textContent ?? "";
    expect(text).toContain("(…)");
    expect(text).not.toContain("(0)");
  });
});

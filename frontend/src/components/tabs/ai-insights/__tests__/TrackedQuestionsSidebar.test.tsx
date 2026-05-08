/**
 * TrackedQuestionsSidebar — Phase D test suite.
 *
 * Covers the sidebar's render branches (loading / error / empty / data),
 * sort order, status colour-coding, and the polling lifecycle (immediate
 * fetch on mount, 30s interval, pause-on-hidden / resume-on-visible).
 *
 * Test runner: vitest 4.x with the jsdom environment configured in
 * frontend/vite.config.ts -> setupFiles=./src/setupTests.ts.
 *
 * Network is mocked via `vi.stubGlobal("fetch", …)`, mirroring the
 * pattern in AIInsightsTab.latest.test.tsx.
 */
import {
  act,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TrackedQuestionsSidebar from "../tracked-questions/TrackedQuestionsSidebar";
import {
  STATUS_CLASS,
  compareQuestions,
} from "../tracked-questions/constants";
import type { OpenQuestion } from "../types";

// --------------------------- helpers ---------------------------

interface MockState {
  body: OpenQuestion[];
  status: number;
  callCount: number;
}

function installFetchMock(initial: OpenQuestion[]): MockState {
  const state: MockState = { body: initial, status: 200, callCount: 0 };
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/insights/open-questions")) {
      state.callCount += 1;
      return {
        ok: state.status >= 200 && state.status < 300,
        status: state.status,
        json: async () => state.body,
      } as Response;
    }
    return { ok: false, status: 404, json: async () => ({}) } as Response;
  });
  vi.stubGlobal("fetch", fn);
  return state;
}

function makeQuestion(overrides: Partial<OpenQuestion> = {}): OpenQuestion {
  return {
    id: "q_default",
    status: "watching",
    materiality: "medium",
    latest_note: "default note body content",
    last_seen_iso: "2026-05-07T12:00:00Z",
    ...overrides,
  };
}

// --------------------------- tests ---------------------------

describe("TrackedQuestionsSidebar", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    // Force visible by default.
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    // Reset hidden flag.
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => false,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("renders the loading skeleton on first paint", async () => {
    // Stub fetch with a never-resolving promise so we stay in the loading
    // branch.
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );

    render(<TrackedQuestionsSidebar />);

    expect(screen.getAllByTestId("tq-skeleton-card")).toHaveLength(3);
  });

  it("renders parsed list of OpenQuestion items as cards", async () => {
    installFetchMock([
      makeQuestion({ id: "q_a", latest_note: "alpha note" }),
      makeQuestion({
        id: "q_b",
        status: "confirmed",
        materiality: "high",
        latest_note: "beta note",
      }),
    ]);

    render(<TrackedQuestionsSidebar />);

    expect(await screen.findByText("q_a")).toBeInTheDocument();
    expect(screen.getByText("q_b")).toBeInTheDocument();
    expect(screen.getByText("alpha note")).toBeInTheDocument();
    expect(screen.getByText("beta note")).toBeInTheDocument();
  });

  it("color-codes status pills with the spec-mandated Tailwind classes", async () => {
    installFetchMock([
      makeQuestion({ id: "q_w", status: "watching" }),
      makeQuestion({ id: "q_c", status: "confirmed" }),
      makeQuestion({ id: "q_d", status: "disproved" }),
      makeQuestion({ id: "q_s", status: "stale" }),
    ]);

    render(<TrackedQuestionsSidebar />);

    await screen.findByText("q_w");

    const watchingCard = screen.getByTestId("tq-card-q_w");
    expect(within(watchingCard).getByText("WATCHING")).toBeInTheDocument();
    expect(
      watchingCard.querySelector('[data-status="watching"]'),
    ).toHaveClass(...STATUS_CLASS.watching.split(" "));

    const confirmedCard = screen.getByTestId("tq-card-q_c");
    expect(
      confirmedCard.querySelector('[data-status="confirmed"]'),
    ).toHaveClass(...STATUS_CLASS.confirmed.split(" "));

    const disprovedCard = screen.getByTestId("tq-card-q_d");
    expect(
      disprovedCard.querySelector('[data-status="disproved"]'),
    ).toHaveClass(...STATUS_CLASS.disproved.split(" "));

    const staleCard = screen.getByTestId("tq-card-q_s");
    expect(
      staleCard.querySelector('[data-status="stale"]'),
    ).toHaveClass(...STATUS_CLASS.stale.split(" "));
  });

  it("renders the empty state when the API returns []", async () => {
    installFetchMock([]);

    render(<TrackedQuestionsSidebar />);

    expect(
      await screen.findByText(
        /No tracked questions yet \u2014 they appear after the agent\u2019s first session\./,
      ),
    ).toBeInTheDocument();
  });

  it("renders an error state with a Retry button on fetch failure", async () => {
    let nextResponse: "throw" | OpenQuestion[] = "throw";
    const fetchFn = vi.fn(async (): Promise<Response> => {
      if (nextResponse === "throw") {
        throw new Error("boom");
      }
      const body = nextResponse;
      return {
        ok: true,
        status: 200,
        json: async () => body,
      } as Response;
    });
    vi.stubGlobal("fetch", fetchFn);

    render(<TrackedQuestionsSidebar />);

    const error = await screen.findByTestId("tq-error");
    expect(error).toBeInTheDocument();
    expect(error.textContent).toMatch(/Couldn\u2019t load tracked questions\./);

    // Now wire a successful response and click Retry.
    nextResponse = [makeQuestion({ id: "q_after_retry" })];

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Retry loading tracked questions" }),
    );

    expect(await screen.findByText("q_after_retry")).toBeInTheDocument();
  });

  it("sorts by status -> materiality -> recency desc", () => {
    const a = makeQuestion({
      id: "a",
      status: "disproved",
      materiality: "high",
      last_seen_iso: "2026-05-07T00:00:00Z",
    });
    const b = makeQuestion({
      id: "b",
      status: "watching",
      materiality: "low",
      last_seen_iso: "2026-04-01T00:00:00Z",
    });
    const c = makeQuestion({
      id: "c",
      status: "watching",
      materiality: "high",
      last_seen_iso: "2026-05-01T00:00:00Z",
    });
    const d = makeQuestion({
      id: "d",
      status: "watching",
      materiality: "high",
      last_seen_iso: "2026-05-05T00:00:00Z",
    });
    const e = makeQuestion({
      id: "e",
      status: "stale",
      materiality: "medium",
      last_seen_iso: "2026-05-06T00:00:00Z",
    });
    const f = makeQuestion({
      id: "f",
      status: "confirmed",
      materiality: "high",
      last_seen_iso: "2026-05-07T00:00:00Z",
    });

    const sorted = [a, b, c, d, e, f].sort(compareQuestions).map((q) => q.id);

    // Expected: watching > confirmed > stale > disproved.
    // Within watching: high > low; within high tied, recency desc.
    expect(sorted).toEqual(["d", "c", "b", "f", "e", "a"]);
  });

  it("polls every 30s and pauses when document is hidden", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const state = installFetchMock([makeQuestion({ id: "q_p" })]);

    render(<TrackedQuestionsSidebar />);

    await waitFor(() => expect(state.callCount).toBeGreaterThanOrEqual(1));
    const callsAfterMount = state.callCount;

    // Advance 30s -> one more fetch.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(state.callCount).toBe(callsAfterMount + 1);

    // Now hide the tab. The interval should pause.
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden",
    });
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => true,
    });
    document.dispatchEvent(new Event("visibilitychange"));

    const callsAfterHide = state.callCount;

    // Advance 60s — no new fetch.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(state.callCount).toBe(callsAfterHide);

    // Resume visible — should fire one immediate fetch and resume the
    // interval.
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => false,
    });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(state.callCount).toBeGreaterThan(callsAfterHide);
  });
});

/**
 * SubscribeButton — Phase E tests.
 *
 * Mirrors the harness style of AIInsightsTab.latest.test.tsx:
 *   - `mockFetch(routes)` helper does substring URL routing, 404+{} default.
 *   - `vi.stubGlobal("fetch", fn)` with a `beforeEach(unstubAllGlobals)`.
 *   - userEvent.setup() drives clicks.
 *
 * Covers, per docs/planning/save-and-history/04-ux-design.md §2.1 / §7:
 *   1. Optimistic flip on click (aria-pressed + label) — POST /subscribe 200.
 *   2. Failure path rolls back + role="alert" toast surfaces error copy.
 *   3. Unsave path (DELETE) — initialSaved=true flips to Save.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SubscribeButton from "../SubscribeButton";

// --------------------------- helpers ---------------------------

interface FetchRoute {
  /** Substring matched against the request URL. First match wins. */
  match: string;
  status?: number;
  body?: unknown;
  /** Optional: limit to a specific HTTP method. */
  method?: string;
}

function mockFetch(routes: FetchRoute[]): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    for (const route of routes) {
      if (route.method && route.method.toUpperCase() !== method) continue;
      if (url.includes(route.match)) {
        const status = route.status ?? 200;
        return {
          ok: status >= 200 && status < 300,
          status,
          json: async () => route.body ?? {},
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

// --------------------------- tests ---------------------------

describe("SubscribeButton", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("optimistically flips to Saved on click and stays Saved after POST 200", async () => {
    mockFetch([
      {
        match: "/api/insights/insights/ins-1/subscribe",
        method: "POST",
        status: 200,
        body: { ok: true },
      },
    ]);

    const onToggle = vi.fn();
    render(
      <SubscribeButton
        insightId="ins-1"
        initialSaved={false}
        onToggle={onToggle}
      />,
    );

    const btn = screen.getByRole("button", { name: /Save this insight/i });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    expect(btn).toHaveTextContent("Save");

    const user = userEvent.setup();
    // Don't await the click — we want to assert the optimistic state before
    // the fetch microtask settles.
    const clickPromise = user.click(btn);

    // The optimistic flip happens synchronously inside `toggle()` before
    // the fetch await yields. The next render reflects aria-pressed="true"
    // and label "Saved".
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Saved/i }),
      ).toHaveAttribute("aria-pressed", "true");
    });
    expect(
      screen.getByRole("button", { name: /Saved/i }),
    ).toHaveTextContent("Saved");

    // Now let the fetch resolve fully.
    await clickPromise;

    // After resolution it stays Saved (success kept the optimistic value).
    const settled = screen.getByRole("button", { name: /Saved/i });
    expect(settled).toHaveAttribute("aria-pressed", "true");
    expect(settled).toHaveTextContent("Saved");
    expect(settled).not.toBeDisabled();

    // onToggle was called with `true` once the toggle settled.
    await waitFor(() => {
      expect(onToggle).toHaveBeenCalledWith(true);
    });
  });

  it("rolls back and shows a role=\"alert\" toast on POST 500", async () => {
    mockFetch([
      {
        match: "/api/insights/insights/ins-2/subscribe",
        method: "POST",
        status: 500,
        body: { error: "boom" },
      },
    ]);

    render(<SubscribeButton insightId="ins-2" initialSaved={false} />);

    const user = userEvent.setup();
    const btn = screen.getByRole("button", { name: /Save this insight/i });
    await user.click(btn);

    // After the failure, the button has rolled back to Save / pressed=false.
    await waitFor(() => {
      const rolled = screen.getByRole("button", { name: /Save this insight/i });
      expect(rolled).toHaveAttribute("aria-pressed", "false");
      expect(rolled).toHaveTextContent("Save");
    });

    // A role="alert" toast is in the DOM with the user-facing copy from §7.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Couldn't save/i);
  });

  it("unsave path: initialSaved=true flips to Save and stays Save on DELETE 200", async () => {
    mockFetch([
      {
        match: "/api/insights/insights/ins-3/subscribe",
        method: "DELETE",
        status: 200,
        body: { ok: true },
      },
    ]);

    const onToggle = vi.fn();
    render(
      <SubscribeButton
        insightId="ins-3"
        initialSaved={true}
        onToggle={onToggle}
      />,
    );

    const btn = screen.getByRole("button", { name: /Saved/i });
    expect(btn).toHaveAttribute("aria-pressed", "true");
    expect(btn).toHaveTextContent("Saved");

    const user = userEvent.setup();
    const clickPromise = user.click(btn);

    // Optimistic flip to Save before the DELETE settles.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Save this insight/i }),
      ).toHaveAttribute("aria-pressed", "false");
    });

    await clickPromise;

    const settled = screen.getByRole("button", { name: /Save this insight/i });
    expect(settled).toHaveAttribute("aria-pressed", "false");
    expect(settled).toHaveTextContent("Save");

    await waitFor(() => {
      expect(onToggle).toHaveBeenCalledWith(false);
    });
  });
});

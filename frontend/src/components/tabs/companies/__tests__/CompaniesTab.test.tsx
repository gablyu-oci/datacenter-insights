/**
 * CompaniesTab — directory search / sort / pagination test suite.
 *
 * Pattern mirrors TrackedQuestionsSidebar.test.tsx: vitest 4 with jsdom,
 * fetch stubbed via `vi.stubGlobal`. We treat /api/companies/aggregate
 * as a noisy-but-benign caller (it goes through useApi) and return a
 * minimal valid envelope so the component renders past its KPI row.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CompaniesTab from "../../CompaniesTab";

// --------------------------- helpers ---------------------------

interface DirectoryCall {
  url: string;
}

interface MockState {
  directoryCalls: DirectoryCall[];
  total: number;
  rows: Array<{
    id: number;
    canonical_name: string;
    short_name: string | null;
    ticker: string | null;
    public_private: string | null;
    site_count: number;
    mw_total: number;
    roles?: { role: string; site_count: number }[];
  }>;
}

function installFetchMock(opts: { total?: number; rows?: MockState["rows"] } = {}): MockState {
  const state: MockState = {
    directoryCalls: [],
    total: opts.total ?? 2,
    rows:
      opts.rows ??
      [
        {
          id: 1,
          canonical_name: "Microsoft",
          short_name: "MSFT",
          ticker: "MSFT",
          public_private: "public",
          site_count: 412,
          mw_total: 6820,
          roles: [{ role: "Tenant", site_count: 200 }],
        },
        {
          id: 2,
          canonical_name: "Google",
          short_name: "GOOG",
          ticker: "GOOGL",
          public_private: "public",
          site_count: 287,
          mw_total: 4210,
          roles: [{ role: "Owner", site_count: 150 }],
        },
      ],
  };

  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/companies/aggregate")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          total_companies: state.total,
          total_sites: 0,
          total_mw: 0,
          stages_included: [],
        }),
      } as Response;
    }
    if (url.includes("/api/companies/")) {
      // CompaniesTab fires a one-shot options fetch (page_size=500) on mount
      // to populate the column-filter popovers. Only the page_size=50 calls
      // are the actual paginated directory fetches we care about asserting on.
      if (!url.includes("page_size=500")) {
        state.directoryCalls.push({ url });
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          data: state.rows,
          total: state.total,
          page: 1,
          page_size: 50,
        }),
      } as Response;
    }
    return { ok: false, status: 404, json: async () => ({}) } as Response;
  });
  vi.stubGlobal("fetch", fn);
  return state;
}

function lastDirectoryUrl(state: MockState): string {
  return state.directoryCalls[state.directoryCalls.length - 1].url;
}

// --------------------------- tests ---------------------------

describe("CompaniesTab", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("test_initial_fetch — issues the default directory request on mount", async () => {
    const state = installFetchMock();

    render(<CompaniesTab />);

    await waitFor(() => expect(state.directoryCalls.length).toBeGreaterThanOrEqual(1));

    const url = state.directoryCalls[0].url;
    expect(url).toContain("/api/companies/?");
    expect(url).toContain("order_by=site_count");
    expect(url).toContain("direction=desc");
    expect(url).toContain("page=1");
    expect(url).toContain("page_size=50");

    expect(await screen.findByText("Microsoft")).toBeInTheDocument();
  });

  it("test_company_popover_tick — opens Company popover, ticks Microsoft, fires names=Microsoft", async () => {
    const state = installFetchMock();
    render(<CompaniesTab />);

    await screen.findByText("Microsoft");
    const baseline = state.directoryCalls.length;

    const user = userEvent.setup();
    const companyHeader = screen.getByRole("columnheader", { name: /^Company/ });
    await user.click(companyHeader);

    // Popover renders the option labels as checkboxes. Ticking one fires
    // the fetch with names=<value>.
    const msftCheckbox = await screen.findByRole("checkbox", { name: /Microsoft/ });
    await user.click(msftCheckbox);

    await waitFor(() => expect(state.directoryCalls.length).toBeGreaterThan(baseline));
    const url = lastDirectoryUrl(state);
    expect(url).toContain("names=Microsoft");
  });

  it("test_company_popover_sort — A→Z button inside Company popover sets order_by=canonical_name&direction=asc", async () => {
    const state = installFetchMock();
    render(<CompaniesTab />);

    await screen.findByText("Microsoft");
    const baseline = state.directoryCalls.length;

    const user = userEvent.setup();
    const companyHeader = screen.getByRole("columnheader", { name: /^Company/ });
    await user.click(companyHeader);

    const azBtn = await screen.findByRole("button", { name: /A→Z/ });
    await user.click(azBtn);

    await waitFor(() => expect(state.directoryCalls.length).toBeGreaterThan(baseline));
    const url = lastDirectoryUrl(state);
    expect(url).toContain("order_by=canonical_name");
    expect(url).toContain("direction=asc");
  });

  it("test_type_popover_tick — ticking Public in Type popover fires public_privates=public", async () => {
    const state = installFetchMock();
    render(<CompaniesTab />);

    await screen.findByText("Microsoft");
    const baseline = state.directoryCalls.length;

    const user = userEvent.setup();
    const typeHeader = screen.getByRole("columnheader", { name: /^Type/ });
    await user.click(typeHeader);

    const publicCheckbox = await screen.findByRole("checkbox", { name: /^public$/ });
    await user.click(publicCheckbox);

    await waitFor(() => expect(state.directoryCalls.length).toBeGreaterThan(baseline));
    const url = lastDirectoryUrl(state);
    expect(url).toContain("public_privates=public");
  });

  it("test_sites_header_toggles_sort — clicking the numeric Sites header still toggles direction", async () => {
    const state = installFetchMock();
    render(<CompaniesTab />);

    await screen.findByText("Microsoft");
    const baseline = state.directoryCalls.length;

    const user = userEvent.setup();
    const sitesHeader = screen.getByRole("columnheader", { name: /^Sites/ });
    // First click: site_count is already the default sort, so it should
    // flip direction to asc.
    await user.click(sitesHeader);

    await waitFor(() => expect(state.directoryCalls.length).toBeGreaterThan(baseline));
    const url = lastDirectoryUrl(state);
    expect(url).toContain("order_by=site_count");
    expect(url).toContain("direction=asc");
  });

  it("test_pagination_click_page_2 — clicking page 2 fires page=2", async () => {
    const state = installFetchMock({ total: 387 });
    render(<CompaniesTab />);

    await screen.findByText("Microsoft");
    const baseline = state.directoryCalls.length;

    const user = userEvent.setup();
    const pageTwo = screen.getByRole("button", { name: "Go to page 2" });
    await user.click(pageTwo);

    await waitFor(() => expect(state.directoryCalls.length).toBeGreaterThan(baseline));
    const url = lastDirectoryUrl(state);
    expect(url).toContain("page=2");
  });

  it("test_pagination_math — renders Showing 1–50 of 387 on page 1 with 8 pages", async () => {
    installFetchMock({ total: 387 });
    render(<CompaniesTab />);

    await screen.findByText("Microsoft");

    // 'Showing 1–50 of 387' (en-dash separator)
    expect(
      screen.getByText((_content, node) =>
        !!node && node.textContent === "Showing 1–50 of 387",
      ),
    ).toBeInTheDocument();

    // totalPages = ceil(387/50) = 8 — the last numbered tile is "8".
    expect(screen.getByRole("button", { name: "Go to page 8" })).toBeInTheDocument();
    // And page 9 should not exist.
    expect(screen.queryByRole("button", { name: "Go to page 9" })).toBeNull();
  });
});

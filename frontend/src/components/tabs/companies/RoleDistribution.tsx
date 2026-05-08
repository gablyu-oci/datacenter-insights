import { useApi } from "../../../hooks/useApi";
import CounterpartyPieCard from "./CounterpartyPieCard";

// ── Types ───────────────────────────────────────────────────────────────────

interface CounterpartySitesEntry {
  company_id: number;
  canonical_name: string;
  count: number;
}

interface CounterpartyMwEntry {
  company_id: number;
  canonical_name: string;
  mw: number;
}

interface CounterpartySide {
  sites: CounterpartySitesEntry[];
  mw: CounterpartyMwEntry[];
  other_sites: number;
  other_mw: number;
}

interface RoleDistributionResponse {
  focal_roles: Record<string, number>;
  pairs: Record<string, Record<string, CounterpartySide>>;
}

// ── Display helpers ─────────────────────────────────────────────────────────

const ROLE_LABEL: Record<string, string> = {
  provider: "Provider",
  end_user: "End user",
  utility: "Utility",
  equipment: "Equipment",
  financing: "Financing",
  provider_backer: "Provider backer",
  developer: "Developer",
  customer: "Customer",
  permittee_llc: "Permittee LLC",
  permit_parent: "Permit parent",
};

const COUNTERPARTY_TITLE: Record<string, string> = {
  provider: "Providers",
  end_user: "End users",
  utility: "Utilities",
  equipment: "Equipment vendors",
  financing: "Financiers",
  provider_backer: "Backers",
  developer: "Developers",
  customer: "Customers",
  permittee_llc: "Permittee LLCs",
  permit_parent: "Permit parents",
};

function roleLabel(role: string): string {
  return ROLE_LABEL[role] ?? role;
}

function counterpartyTitle(role: string): string {
  return COUNTERPARTY_TITLE[role] ?? role;
}

// ── Component ───────────────────────────────────────────────────────────────

export default function RoleDistribution({
  companyId,
  companyName,
}: {
  companyId: number;
  companyName: string;
}) {
  const { data, loading, error } = useApi<RoleDistributionResponse>(
    `/api/companies/${companyId}/role-distribution`,
  );

  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ color: "#64748b", fontSize: 11, marginBottom: 10 }}>
        For each role this company holds, who shows up on the same sites in other roles.
      </div>

      {error ? (
        <div style={{ color: "#ef4444", fontSize: 13, padding: "12px 0" }}>
          Failed to load role distribution.
        </div>
      ) : loading || !data ? (
        <div style={{ color: "#3b82f6", fontSize: 12, padding: "12px 0" }}>
          Loading role distribution...
        </div>
      ) : Object.keys(data.pairs).length === 0 ? (
        <div style={{ color: "#94a3b8", fontSize: 12, padding: "12px 0" }}>
          No counterparty data found for this company.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {Object.entries(data.pairs)
            .sort(([a], [b]) => (data.focal_roles[b] ?? 0) - (data.focal_roles[a] ?? 0))
            .map(([myRole, theirSides]) => (
              <div key={myRole}>
                <div
                  style={{
                    color: "#cbd5e1",
                    fontSize: 12,
                    fontWeight: 600,
                    marginBottom: 8,
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                  }}
                >
                  <span>When this company is {roleLabel(myRole).toLowerCase()}</span>
                  <span
                    style={{
                      color: "#64748b",
                      fontSize: 10,
                      fontWeight: 400,
                    }}
                  >
                    ({data.focal_roles[myRole] ?? 0} sites)
                  </span>
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: 12,
                    flexWrap: "wrap",
                    alignItems: "stretch",
                  }}
                >
                  {Object.entries(theirSides)
                    .sort(([, a], [, b]) => (b.other_sites + b.sites.length) - (a.other_sites + a.sites.length))
                    .map(([theirRole, side]) => (
                      <CounterpartyPieCard
                        key={`${myRole}->${theirRole}`}
                        title={counterpartyTitle(theirRole)}
                        subtitle={`${roleLabel(theirRole)} role`}
                        sitesData={side.sites}
                        mwData={side.mw}
                        otherSites={side.other_sites}
                        otherMw={side.other_mw}
                        companyName={companyName}
                      />
                    ))}
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

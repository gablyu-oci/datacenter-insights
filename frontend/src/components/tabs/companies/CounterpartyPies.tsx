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

interface CounterpartiesResponse {
  as_provider: CounterpartySide;
  as_end_user: CounterpartySide;
}

// ── Component ───────────────────────────────────────────────────────────────

export default function CounterpartyPies({
  companyId,
  companyName,
}: {
  companyId: number;
  companyName: string;
}) {
  const { data, loading, error } = useApi<CounterpartiesResponse>(
    `/api/companies/${companyId}/counterparties`,
  );

  return (
    <div style={{ marginBottom: 20 }}>
      {/* Section header */}
      <div
        style={{
          color: "#94a3b8",
          fontSize: "11px",
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          marginBottom: 4,
        }}
      >
        Counterparties
      </div>
      <div style={{ color: "#64748b", fontSize: 11, marginBottom: 10 }}>
        Buyers when this company supplies (utility / equipment / financing / developer)
        &middot; Sellers when this company operates a site (provider / end-user)
      </div>

      {error ? (
        <div
          style={{
            color: "#ef4444",
            fontSize: 13,
            padding: "20px 0",
            textAlign: "center",
          }}
        >
          Failed to load counterparties.
        </div>
      ) : loading || !data ? (
        <div
          style={{
            color: "#3b82f6",
            textAlign: "center",
            padding: "20px 0",
            fontSize: 12,
          }}
        >
          Loading counterparties...
        </div>
      ) : (
        <div
          style={{
            display: "flex",
            gap: 16,
            flexWrap: "wrap",
            alignItems: "stretch",
          }}
        >
          <CounterpartyPieCard
            title="Buyers"
            subtitle="When this company supplies"
            sitesData={data.as_provider.sites}
            mwData={data.as_provider.mw}
            otherSites={data.as_provider.other_sites}
            otherMw={data.as_provider.other_mw}
            companyName={companyName}
          />
          <CounterpartyPieCard
            title="Sellers"
            subtitle="When this company operates a site"
            sitesData={data.as_end_user.sites}
            mwData={data.as_end_user.mw}
            otherSites={data.as_end_user.other_sites}
            otherMw={data.as_end_user.other_mw}
            companyName={companyName}
          />
        </div>
      )}
    </div>
  );
}

import { useApi } from "../../hooks/useApi";
import ErrorPanel from "./ErrorPanel";

interface RoleCompany {
  company_id: number;
  canonical_name: string;
  short_name: string | null;
  ticker: string | null;
  confidence: number | null;
  source: string | null;
}

type RoleSummaryResponse = Record<string, RoleCompany[]>;

const ROLE_COLORS: Record<string, string> = {
  provider: "#3b82f6",
  end_user: "#22c55e",
  developer: "#f59e0b",
  operator: "#8b5cf6",
  owner: "#06b6d4",
  investor: "#ec4899",
  utility: "#f97316",
};

interface SiteRoleBreakdownProps {
  siteUid: string;
  onCompanyClick?: (companyId: number) => void;
}

export default function SiteRoleBreakdown({ siteUid, onCompanyClick }: SiteRoleBreakdownProps) {
  const { data, loading, error, errorInfo, retry } = useApi<RoleSummaryResponse>(`/api/sites/${siteUid}/role-summary`);

  if (loading) {
    return (
      <div style={{ color: "#3b82f6", fontSize: "12px", padding: "12px 0" }}>
        Loading role breakdown...
      </div>
    );
  }

  if (error) {
    return <ErrorPanel title={errorInfo?.title} message={errorInfo?.message} onRetry={retry} variant="inline" />;
  }

  if (!data || Object.keys(data).length === 0) {
    return (
      <div style={{ color: "#64748b", fontSize: "12px", padding: "8px 0" }}>
        No role data available for this site.
      </div>
    );
  }

  return (
    <div>
      <div style={{
        color: "#94a3b8",
        fontSize: "11px",
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        marginBottom: 10,
      }}>
        Companies by Role
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {Object.entries(data).map(([role, companies]) => {
          const roleColor = ROLE_COLORS[role.toLowerCase()] ?? "#64748b";
          const companyList: RoleCompany[] = Array.isArray(companies) ? companies : [];

          return (
            <div key={role}>
              <div style={{
                color: roleColor,
                fontSize: "10px",
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.04em",
                marginBottom: 4,
              }}>
                {role}
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {companyList.length === 0 ? (
                  <span style={{ color: "#475569", fontSize: "11px" }}>&mdash;</span>
                ) : (
                  companyList.map((c) => (
                    <button
                      key={c.company_id}
                      onClick={() => onCompanyClick?.(c.company_id)}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 4,
                        padding: "3px 10px",
                        borderRadius: "16px",
                        background: `${roleColor}18`,
                        border: `1px solid ${roleColor}44`,
                        color: roleColor,
                        fontSize: "11px",
                        fontWeight: 500,
                        cursor: onCompanyClick ? "pointer" : "default",
                      }}
                    >
                      {c.canonical_name || c.short_name || "Unknown"}
                      {c.ticker && (
                        <span style={{ color: "#475569", fontSize: "9px" }}>({c.ticker})</span>
                      )}
                    </button>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

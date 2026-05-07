import { Activity, Database, Zap } from "lucide-react";
import { useApi } from "../../hooks/useApi";

interface HealthPayload {
  status: string;
  version: string;
  db: string;
  llama_stack: string;
  agents_active: number;
  last_sync: string | null;
}

function formatLastSync(iso: string | null): string {
  if (!iso) return "no runs yet";
  const ts = new Date(iso);
  const ageMs = Date.now() - ts.getTime();
  const minutes = Math.floor(ageMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return ts.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export default function Header() {
  const { data, error } = useApi<HealthPayload>("/api/health");

  const agentsLabel =
    error ? "agents —" :
    data == null ? "agents …" :
    `${data.agents_active} agent${data.agents_active === 1 ? "" : "s"} active`;

  const syncLabel =
    error ? "sync —" :
    data == null ? "sync …" :
    `Last sync: ${formatLastSync(data.last_sync)}`;

  const agentDotColor = error ? "#ef4444" : data == null ? "#94a3b8" : "#22c55e";

  return (
    <header style={{
      background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
      borderBottom: "1px solid #334155",
      padding: "0 24px",
      height: "60px",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
        <div style={{
          background: "linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)",
          borderRadius: "8px",
          padding: "6px",
          display: "flex",
        }}>
          <Zap size={18} color="white" />
        </div>
        <div>
          <span style={{ color: "white", fontWeight: 700, fontSize: "16px", letterSpacing: "-0.3px" }}>
            Datacenter & Power Intelligence
          </span>
          <span style={{ color: "#64748b", fontSize: "12px", marginLeft: "8px" }}>
            OCI Strategic Platform
          </span>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
        <div
          style={{ display: "flex", alignItems: "center", gap: "6px" }}
          title="Count of scheduled adapter jobs registered in pipeline/runner.JOB_CONFIG."
        >
          <Activity size={14} color={agentDotColor} />
          <span style={{ color: "#94a3b8", fontSize: "12px" }}>{agentsLabel}</span>
        </div>
        <div
          style={{ display: "flex", alignItems: "center", gap: "6px" }}
          title={data?.last_sync ? `Most recent successful adapter run at ${data.last_sync}` : "No adapter runs recorded yet."}
        >
          <Database size={14} color="#3b82f6" />
          <span style={{ color: "#94a3b8", fontSize: "12px" }}>{syncLabel}</span>
        </div>
      </div>
    </header>
  );
}

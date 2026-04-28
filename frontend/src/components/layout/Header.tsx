import { Activity, Database, Zap } from "lucide-react";

export default function Header() {
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
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <Activity size={14} color="#22c55e" />
          <span style={{ color: "#94a3b8", fontSize: "12px" }}>8 Agents Active</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <Database size={14} color="#3b82f6" />
          <span style={{ color: "#94a3b8", fontSize: "12px" }}>Last sync: Dec 15, 2024</span>
        </div>
      </div>
    </header>
  );
}

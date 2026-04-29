const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

interface NoDataPanelProps {
  pillar: string;
  reason?: string;
}

export default function NoDataPanel({ pillar, reason }: NoDataPanelProps) {
  return (
    <div style={{ ...CARD_STYLE, textAlign: "center", padding: "60px 20px" }}>
      <div style={{ color: "#475569", fontSize: "32px", marginBottom: "12px" }}>
        {/* bar chart icon via unicode */}
        &#x1F4CA;
      </div>
      <div style={{ color: "#94a3b8", fontSize: "14px", marginBottom: "8px" }}>
        No {pillar} data available yet
      </div>
      <div style={{ color: "#64748b", fontSize: "12px" }}>
        {reason || "This data source will be integrated in a future phase."}
      </div>
    </div>
  );
}

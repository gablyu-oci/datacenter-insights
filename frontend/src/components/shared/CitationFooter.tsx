import { ExternalLink } from "lucide-react";

interface CitationFooterProps {
  sources?: string[];
  retrievedAt?: string | null;
  confidence?: number | null;
  sourceUrl?: string | null;
}

export default function CitationFooter({
  sources,
  retrievedAt,
  confidence,
  sourceUrl,
}: CitationFooterProps) {
  const hasSources = sources && sources.length > 0;
  const hasAny = hasSources || retrievedAt || confidence != null;

  if (!hasAny) return null;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "12px",
        flexWrap: "wrap",
        padding: "8px 0 0",
        marginTop: "8px",
        borderTop: "1px solid #1e293b",
        fontSize: "10px",
        color: "#64748b",
      }}
    >
      {hasSources && (
        <span>
          Source:{" "}
          {sourceUrl ? (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noreferrer"
              style={{
                color: "#3b82f6",
                textDecoration: "none",
                display: "inline-flex",
                alignItems: "center",
                gap: "3px",
              }}
            >
              {sources.join(", ")}
              <ExternalLink size={8} />
            </a>
          ) : (
            <span style={{ color: "#94a3b8" }}>{sources.join(", ")}</span>
          )}
        </span>
      )}
      {retrievedAt && (
        <span>Retrieved: {retrievedAt.split("T")[0]}</span>
      )}
      {confidence != null && (
        <span>
          Confidence:{" "}
          <span
            style={{
              color:
                confidence >= 0.8
                  ? "#4ade80"
                  : confidence >= 0.5
                    ? "#fbbf24"
                    : "#f87171",
            }}
          >
            {(confidence * 100).toFixed(0)}%
          </span>
        </span>
      )}
    </div>
  );
}

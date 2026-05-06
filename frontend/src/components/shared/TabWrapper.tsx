import type { ReactNode } from "react";
import CoverageBadge from "./CoverageBadge";

interface TabWrapperProps {
  pillar: string;
  children: ReactNode;
}

// Tabs whose content is generative/derived rather than ingested data.
// CoverageBadge would always say "No Data" for these (no data_coverage
// row exists) and overlap the Run-again button visually.
const PILLARS_WITHOUT_COVERAGE = new Set(["AI Insights"]);

export default function TabWrapper({ pillar, children }: TabWrapperProps) {
  const showCoverage = !PILLARS_WITHOUT_COVERAGE.has(pillar);
  return (
    <div style={{ position: "relative" }}>
      {showCoverage ? (
        <div
          style={{
            position: "absolute",
            top: "12px",
            right: "24px",
            zIndex: 10,
          }}
        >
          <CoverageBadge pillar={pillar} />
        </div>
      ) : null}
      {children}
    </div>
  );
}

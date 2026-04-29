import type { ReactNode } from "react";
import CoverageBadge from "./CoverageBadge";

interface TabWrapperProps {
  pillar: string;
  children: ReactNode;
}

export default function TabWrapper({ pillar, children }: TabWrapperProps) {
  return (
    <div style={{ position: "relative" }}>
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
      {children}
    </div>
  );
}

import { useState } from "react";
import Header from "./components/layout/Header";
import TabNav from "./components/layout/TabNav";
import TabWrapper from "./components/shared/TabWrapper";
import PowerTab from "./components/tabs/PowerTab";
import DataCentersTab from "./components/tabs/DataCentersTab";
import GPUSupplyTab from "./components/tabs/GPUSupplyTab";
import NICsOpticsTab from "./components/tabs/NICsOpticsTab";
import TSMCTab from "./components/tabs/TSMCTab";
import PermitsTab from "./components/tabs/PermitsTab";
import TriangulationTab from "./components/tabs/TriangulationTab";
import SourcesTab from "./components/tabs/SourcesTab";
import CompaniesTab from "./components/tabs/CompaniesTab";
import ChatPanel from "./components/ChatPanel";

const TAB_CONFIG: Record<string, { element: React.ReactNode; pillar: string }> = {
  power: { element: <PowerTab />, pillar: "Power" },
  datacenters: { element: <DataCentersTab />, pillar: "Sites" },
  gpu: { element: <GPUSupplyTab />, pillar: "GPU Supply" },
  nics: { element: <NICsOpticsTab />, pillar: "NICs & Optics" },
  tsmc: { element: <TSMCTab />, pillar: "TSMC" },
  permits: { element: <PermitsTab />, pillar: "Permits" },
  triangulation: { element: <TriangulationTab />, pillar: "Triangulation" },
  companies: { element: <CompaniesTab />, pillar: "Companies" },
  sources: { element: <SourcesTab />, pillar: "Sources" },
};

export default function App() {
  const [activeTab, setActiveTab] = useState<keyof typeof TAB_CONFIG>("datacenters");

  const config = TAB_CONFIG[activeTab] ?? TAB_CONFIG.datacenters;

  return (
    <div style={{
      minHeight: "100vh",
      background: "#0f172a",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      color: "white",
    }}>
      <Header />
      <TabNav active={activeTab as string} onChange={(id) => setActiveTab(id as keyof typeof TAB_CONFIG)} />
      <main style={{ overflowY: "auto" }}>
        <TabWrapper pillar={config.pillar}>
          {config.element}
        </TabWrapper>
      </main>
      <ChatPanel />
    </div>
  );
}

import { useState } from "react";
import Header from "./components/layout/Header";
import TabNav from "./components/layout/TabNav";
import PowerTab from "./components/tabs/PowerTab";
import DataCentersTab from "./components/tabs/DataCentersTab";
import SatelliteTab from "./components/tabs/SatelliteTab";
import GPUSupplyTab from "./components/tabs/GPUSupplyTab";
import NICsOpticsTab from "./components/tabs/NICsOpticsTab";
import TSMCTab from "./components/tabs/TSMCTab";
import PermitsTab from "./components/tabs/PermitsTab";
import TriangulationTab from "./components/tabs/TriangulationTab";
import SourcesTab from "./components/tabs/SourcesTab";

const TAB_CONTENT = {
  power: <PowerTab />,
  datacenters: <DataCentersTab />,
  satellite: <SatelliteTab />,
  gpu: <GPUSupplyTab />,
  nics: <NICsOpticsTab />,
  tsmc: <TSMCTab />,
  permits: <PermitsTab />,
  triangulation: <TriangulationTab />,
  sources: <SourcesTab />,
};

export default function App() {
  const [activeTab, setActiveTab] = useState<keyof typeof TAB_CONTENT>("power");

  return (
    <div style={{
      minHeight: "100vh",
      background: "#0f172a",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      color: "white",
    }}>
      <Header />
      <TabNav active={activeTab} onChange={(id) => setActiveTab(id as keyof typeof TAB_CONTENT)} />
      <main style={{ overflowY: "auto" }}>
        {TAB_CONTENT[activeTab]}
      </main>
    </div>
  );
}

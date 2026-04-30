import { useState, useRef, useEffect } from "react";
import { Zap, Cpu, Network, Microchip, FileText, GitBranch, BookOpen, ChevronDown, Package, Server, Building2 } from "lucide-react";

// Top-level tabs rendered before the Supplier Insights dropdown.
// Data Centers is first (the primary entry point — Aterio site map + table).
// Q&A used to be a tab; now lives in the floating ChatPanel widget.
const TOP_TABS = [
  { id: "datacenters", label: "Data Centers Overview", icon: Server, real: true },
  { id: "power",       label: "Power Contracts",       icon: Zap,    real: true },
];

const SUPPLIER_TABS = [
  { id: "gpu",  label: "GPU Supply",               icon: Cpu,       real: true },
  { id: "nics", label: "NICs & Optics Supply",     icon: Network,   real: true },
  { id: "tsmc", label: "Wafer Production & Supply", icon: Microchip, real: true },
];

const AFTER_SUPPLIER = [
  { id: "permits",       label: "Country Permits", icon: FileText,   real: true  },
  { id: "companies",     label: "Companies",       icon: Building2,  real: true  },
  { id: "triangulation", label: "Triangulation",   icon: GitBranch,  real: false },
  { id: "sources",       label: "Data Sources",    icon: BookOpen,   real: true  },
];

const SUPPLIER_IDS = new Set(SUPPLIER_TABS.map(t => t.id));

interface TabNavProps {
  active: string;
  onChange: (id: string) => void;
}

const BADGE = (real: boolean) => (
  <span style={{
    padding: "1px 5px", borderRadius: "3px", fontSize: "9px", fontWeight: 600,
    letterSpacing: "0.04em", marginLeft: "2px",
    background: real ? "#052e16" : "#1c1917",
    border: `1px solid ${real ? "#16a34a" : "#44403c"}`,
    color: real ? "#4ade80" : "#78716c",
  }}>
    {real ? "LIVE" : "MOCK"}
  </span>
);

export default function TabNav({ active, onChange }: TabNavProps) {
  const [supplierOpen, setSupplierOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const supplierActive = SUPPLIER_IDS.has(active);

  useEffect(() => {
    function onMouseDown(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setSupplierOpen(false);
      }
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, []);

  const renderTab = (id: string, label: string, Icon: React.ElementType, real: boolean) => {
    const isActive = active === id;
    return (
      <button
        key={id}
        onClick={() => onChange(id)}
        style={{
          display: "flex", alignItems: "center", gap: "6px",
          padding: "12px 16px",
          color: isActive ? "#3b82f6" : "#94a3b8",
          background: "none", border: "none",
          borderBottom: isActive ? "2px solid #3b82f6" : "2px solid transparent",
          cursor: "pointer", fontSize: "13px",
          fontWeight: isActive ? 600 : 400,
          whiteSpace: "nowrap", transition: "color 0.15s",
        }}
      >
        <Icon size={14} />
        {label}
        {BADGE(real)}
      </button>
    );
  };

  return (
    // overflow must be visible so the dropdown panel isn't clipped by the nav
    <nav style={{
      background: "#0f172a",
      borderBottom: "1px solid #1e293b",
      display: "flex",
      padding: "0 24px",
      position: "relative",
      overflow: "visible",
    }}>

      {TOP_TABS.map(({ id, label, icon: Icon, real }) => renderTab(id, label, Icon, real))}

      {/* ── Supplier Insights dropdown ── */}
      <div ref={dropdownRef} style={{ position: "relative", display: "flex", alignItems: "stretch" }}>
        <button
          onClick={() => setSupplierOpen(v => !v)}
          style={{
            display: "flex", alignItems: "center", gap: "6px",
            padding: "12px 16px",
            color: supplierActive || supplierOpen ? "#3b82f6" : "#94a3b8",
            background: "none", border: "none",
            borderBottom: supplierActive ? "2px solid #3b82f6" : "2px solid transparent",
            cursor: "pointer", fontSize: "13px",
            fontWeight: supplierActive ? 600 : 400,
            whiteSpace: "nowrap", transition: "color 0.15s",
          }}
        >
          <Package size={14} />
          Supplier Insights
          {BADGE(false)}
          <ChevronDown
            size={12}
            style={{ marginLeft: 2, transition: "transform 0.15s", transform: supplierOpen ? "rotate(180deg)" : "rotate(0deg)" }}
          />
        </button>

        {supplierOpen && (
          <div style={{
            position: "absolute",
            top: "calc(100% + 1px)",
            left: 0,
            zIndex: 9999,
            background: "#0f172a",
            border: "1px solid #334155",
            borderTop: "2px solid #3b82f6",
            borderRadius: "0 0 10px 10px",
            boxShadow: "0 16px 40px rgba(0,0,0,0.6)",
            minWidth: 230,
            padding: "4px 0 8px",
          }}>
            {SUPPLIER_TABS.map(({ id, label, icon: Icon }) => {
              const isActive = active === id;
              return (
                <button
                  key={id}
                  onClick={() => { onChange(id); setSupplierOpen(false); }}
                  style={{
                    display: "flex", alignItems: "center", gap: "8px",
                    width: "100%", padding: "10px 18px",
                    background: isActive ? "#1e293b" : "transparent",
                    border: "none",
                    borderLeft: isActive ? "3px solid #3b82f6" : "3px solid transparent",
                    color: isActive ? "#60a5fa" : "#94a3b8",
                    cursor: "pointer", fontSize: "13px",
                    fontWeight: isActive ? 600 : 400,
                    textAlign: "left", transition: "background 0.1s",
                  }}
                >
                  <Icon size={13} />
                  {label}
                  <span style={{
                    marginLeft: "auto", padding: "1px 5px", borderRadius: "3px",
                    fontSize: "9px", fontWeight: 600,
                    background: "#1c1917", border: "1px solid #44403c", color: "#78716c",
                  }}>
                    MOCK
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {AFTER_SUPPLIER.map(({ id, label, icon: Icon, real }) => renderTab(id, label, Icon, real))}
    </nav>
  );
}

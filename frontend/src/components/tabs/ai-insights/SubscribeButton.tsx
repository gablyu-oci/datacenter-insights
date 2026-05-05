import { useCallback, useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";

/**
 * SubscribeButton — V3 scaffold (per kickoff: button visible, says
 * "V3 — coming soon" on click). Best-effort POSTs to the backend
 * subscription endpoint so future V3 work has the row already written;
 * regardless of response (success/failure), the user-visible affordance
 * is the inline toast.
 */

const c = tokens.color;
const t = tokens.typography;
const r = tokens.radius;

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

const TOAST_MS = 3000;

export interface SubscribeButtonProps {
  insightId: string;
}

export default function SubscribeButton({ insightId }: SubscribeButtonProps) {
  const [showToast, setShowToast] = useState(false);
  const [busy, setBusy] = useState(false);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  }, []);

  const onClick = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    // Best-effort write; ignore response shape entirely. The UX is the toast.
    try {
      await fetch(
        `${API_BASE}/api/insights/insights/${encodeURIComponent(insightId)}/subscribe`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        },
      );
    } catch {
      // Backend may not yet implement this endpoint — that's expected for V2.
    }
    setBusy(false);
    setShowToast(true);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setShowToast(false), TOAST_MS);
  }, [busy, insightId]);

  return (
    <span
      style={{ position: "relative", display: "inline-flex", alignItems: "center" }}
    >
      <button
        type="button"
        onClick={onClick}
        aria-label="subscribe to this insight"
        disabled={busy}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          height: 32,
          padding: "0 12px",
          background: c.bg.card,
          color: c.text.muted,
          border: `1px solid ${c.border.default}`,
          borderRadius: r.md,
          fontSize: t.body.fontSize,
          fontWeight: 500,
          cursor: busy ? "not-allowed" : "pointer",
          fontFamily: "inherit",
        }}
      >
        <Bell size={14} aria-hidden="true" />
        Subscribe
      </button>
      {showToast ? (
        <span
          role="status"
          aria-live="polite"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            background: c.brand.tintDark,
            color: c.brand.primaryHover,
            border: `1px solid ${c.brand.primaryDeep}`,
            borderRadius: r.md,
            padding: "6px 10px",
            fontSize: t.meta.fontSize,
            whiteSpace: "nowrap",
            boxShadow: tokens.shadow.popover,
            zIndex: 50,
          }}
        >
          V3 — coming soon
        </span>
      ) : null}
    </span>
  );
}

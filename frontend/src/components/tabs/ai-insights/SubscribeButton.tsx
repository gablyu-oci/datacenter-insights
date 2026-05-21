import { useCallback, useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";
import { useInsightSubscription } from "../../../hooks/useInsightSubscription";

/**
 * SubscribeButton — Save toggle (Phase D rewrite of the V3 placeholder).
 *
 * Renders a bell icon + label inside each `InsightCard`. Uses
 * `useInsightSubscription` for the optimistic POST/DELETE flow against
 * `/api/insights/insights/{insight_id}/subscribe`.
 *
 * UX contract per docs/planning/save-and-history/04-ux-design.md §2.1:
 *   - Outline bell + "Save" label when not saved.
 *   - Filled bell (fill = brand.primary) + "Saved" label when saved.
 *   - aria-pressed reflects current saved state.
 *   - While `pending` the button is disabled (opacity 0.6, pointer-events none).
 *   - On failed toggle the hook surfaces an `error` string — we render it as
 *     a popover-style inline toast with role="alert" that auto-dismisses
 *     after 4 seconds. Visual matches the prior V3 toast treatment.
 */

const c = tokens.color;
const t = tokens.typography;
const r = tokens.radius;
const s = tokens.spacing;

const TOAST_MS = 4000;

const TOOLTIP_UNSAVED = "Save this insight";
const TOOLTIP_SAVED = "Saved — click to remove";
const TOOLTIP_PENDING = "Saving…";

const LABEL_UNSAVED = "Save";
const LABEL_SAVED = "Saved";

export interface SubscribeButtonProps {
  insightId: string;
  /** Seeded from backend `is_saved`. Defaults to false. */
  initialSaved?: boolean;
  /**
   * Fires after a successful toggle resolves (used by SavedInsightsSection
   * to refetch when a row is un-saved from inside the list).
   */
  onToggle?: (next: boolean) => void;
}

export default function SubscribeButton({
  insightId,
  initialSaved = false,
  onToggle,
}: SubscribeButtonProps) {
  const subscription = useInsightSubscription(insightId, initialSaved);
  const { saved, pending, error, toggle } = subscription;

  const [toastVisible, setToastVisible] = useState<boolean>(false);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // When the hook surfaces an error string, show the toast for TOAST_MS.
  useEffect(() => {
    if (!error) return;
    setToastVisible(true);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToastVisible(false), TOAST_MS);
  }, [error]);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  }, []);

  const onClick = useCallback(async () => {
    if (pending) return;
    const previous = saved;
    await toggle();
    // After the await resolves, if the hook did NOT record an error, the
    // optimistic flip stuck and we should notify the parent. We read the
    // error via the hook's freshest state on the next render rather than
    // a closure: we approximate by checking that `saved` flipped — but a
    // safer signal is to read from the hook's `subscription.error` value
    // after the awaited toggle settles. The hook clears `error` to null on
    // success. So: re-read subscription via ref.
    // The `toggle` promise resolves AFTER setError has been called (either
    // null on success or the failure message on revert); React will batch
    // and the next render reflects this. To avoid relying on the next
    // render, we use a microtask-resolved check via `subscription.error`
    // which is closed over the current render. We instead defer the
    // notification to a useEffect-style watch: parent gets notified via
    // an effect below when `saved` changes.
    void previous; // keep `previous` referenced for clarity / future use.
  }, [pending, saved, toggle]);

  // Notify parent when the saved state changes as a result of a settled
  // toggle (not just the initial seed). We dedupe with a ref so the first
  // render does NOT fire onToggle.
  const lastNotifiedRef = useRef<boolean>(initialSaved);
  useEffect(() => {
    if (pending) return;
    if (lastNotifiedRef.current === saved) return;
    lastNotifiedRef.current = saved;
    onToggle?.(saved);
  }, [saved, pending, onToggle]);

  const tooltip = pending
    ? TOOLTIP_PENDING
    : saved
      ? TOOLTIP_SAVED
      : TOOLTIP_UNSAVED;
  const label = saved ? LABEL_SAVED : LABEL_UNSAVED;

  // Color / border / bg follow §2.1 + §3.3 of 04-ux-design.md.
  const buttonBg = saved ? c.brand.tintDark : "transparent";
  const buttonBorder = saved ? c.brand.primary : c.border.default;
  const buttonColor = saved ? c.text.primary : c.text.muted;
  const bellFill = saved ? c.brand.primary : "none";
  const bellColor = saved ? c.brand.primary : c.text.caption;

  return (
    <span
      style={{ position: "relative", display: "inline-flex", alignItems: "center" }}
    >
      <button
        type="button"
        onClick={onClick}
        aria-pressed={saved}
        aria-label={saved ? TOOLTIP_SAVED : TOOLTIP_UNSAVED}
        title={tooltip}
        disabled={pending}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: s.s1,
          padding: `${s.s1}px ${s.s2}px`,
          background: buttonBg,
          color: buttonColor,
          border: `1px solid ${buttonBorder}`,
          borderRadius: r.md,
          fontSize: t.caption.fontSize,
          fontWeight: t.caption.fontWeight,
          fontFamily: "inherit",
          cursor: pending ? "not-allowed" : "pointer",
          opacity: pending ? 0.6 : 1,
          pointerEvents: pending ? "none" : "auto",
          transition: `${tokens.motion.transitionColor}, ${tokens.motion.transitionBg}`,
        }}
      >
        <Bell
          size={14}
          aria-hidden="true"
          fill={bellFill}
          color={bellColor}
        />
        {label}
      </button>
      {toastVisible && error ? (
        <span
          role="alert"
          aria-live="assertive"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            background: c.bg.card,
            color: c.text.body,
            borderLeft: `3px solid ${c.semantic.danger}`,
            border: `1px solid ${c.border.default}`,
            borderLeftWidth: 3,
            borderLeftColor: c.semantic.danger,
            borderRadius: r.md,
            padding: `${s.s2}px ${s.s3}px`,
            fontSize: t.caption.fontSize,
            whiteSpace: "nowrap",
            boxShadow: tokens.shadow.popover,
            zIndex: 50,
          }}
        >
          {error}
        </span>
      ) : null}
    </span>
  );
}

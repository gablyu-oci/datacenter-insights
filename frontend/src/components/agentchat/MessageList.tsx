import {
  useEffect,
  useLayoutEffect,
  useRef,
  type CSSProperties,
  type ReactNode,
} from "react";
import { tokens } from "../../styles/insightTokens";

/**
 * MessageList — scroll-managed container for a chat-style message stream.
 *
 *  - Auto-scrolls to the bottom when the user is "pinned" (scrolled to /
 *    near the bottom). If the user has scrolled up to read older content,
 *    we DO NOT yank them back down on every new token — that's the
 *    UX-correctness improvement called out in RESEARCH §5.2.
 *
 *  - Re-runs the auto-scroll check on every children update so a streaming
 *    transcript animates correctly while still respecting the pinned state.
 *
 *  - Intentionally agnostic about the message shape — children are rendered
 *    verbatim. Use with `MessageBubble` (or any primitive) above.
 */

const c = tokens.color;
const s = tokens.spacing;

const PIN_THRESHOLD_PX = 64;

export interface MessageListProps {
  children: ReactNode;
  /**
   * Bumped every time the message tree could have grown, to trigger the
   * pinned auto-scroll check. Pass `messages.length` or a string version
   * stamp (e.g. `${messages.length}-${streamingTokens}`).
   */
  scrollKey: string | number;
  /** Override list height. Defaults to 100% of the parent (flex child). */
  height?: string | number;
  /** Pad the inner scroll area. Default: 14px 16px. */
  padding?: string | number;
  /** Inline style passthrough on the outer scrolling div. */
  style?: CSSProperties;
  /** ARIA label; helps screen readers identify the live region. */
  ariaLabel?: string;
}

export default function MessageList({
  children,
  scrollKey,
  height,
  padding,
  style,
  ariaLabel = "message list",
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);

  // Track whether the user is pinned to the bottom (within threshold).
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      pinnedRef.current = distance < PIN_THRESHOLD_PX;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // After every render that could have grown the list, snap to bottom IFF
  // pinned. useLayoutEffect avoids a flicker on appended messages.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (pinnedRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [scrollKey]);

  return (
    <div
      ref={scrollRef}
      role="log"
      aria-label={ariaLabel}
      aria-live="polite"
      style={{
        flex: 1,
        height,
        overflowY: "auto",
        padding: padding ?? `${s.s4}px ${s.s4}px`,
        display: "flex",
        flexDirection: "column",
        gap: s.s3,
        background: c.bg.page,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

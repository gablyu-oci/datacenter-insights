import type { CSSProperties } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { tokens } from "../../styles/insightTokens";

/**
 * MarkdownRenderer — react-markdown wrapper with the dark-theme component
 * overrides previously inlined in `ChatPanel.tsx` (lines 21–85).
 *
 * Sanitization preset notes:
 *   - We rely on react-markdown's default deny-list (it strips raw HTML by
 *     default and blocks `javascript:` URLs).
 *   - All anchor tags are forced to `target="_blank"` + `rel="noreferrer"`
 *     so untrusted markdown can't redirect the parent frame.
 *   - GFM is enabled via `remark-gfm` for tables / strikethrough / autolinks.
 */

const c = tokens.color;
const t = tokens.typography;

const MD_COMPONENTS = {
  p: (props: React.HTMLAttributes<HTMLParagraphElement>) => (
    <p {...props} style={{ margin: "0 0 8px", lineHeight: 1.55 }} />
  ),
  strong: (props: React.HTMLAttributes<HTMLElement>) => (
    <strong {...props} style={{ color: c.text.primary, fontWeight: 600 }} />
  ),
  em: (props: React.HTMLAttributes<HTMLElement>) => (
    <em {...props} style={{ color: c.text.muted, fontStyle: "italic" }} />
  ),
  code: (props: React.HTMLAttributes<HTMLElement>) => (
    <code
      {...props}
      style={{
        background: c.bg.surface,
        padding: "1px 5px",
        borderRadius: 3,
        fontSize: "0.92em",
        fontFamily: t.mono.fontFamily,
      }}
    />
  ),
  a: (props: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a
      {...props}
      target="_blank"
      rel="noreferrer noopener"
      style={{ color: c.brand.primaryHover, textDecoration: "underline" }}
    />
  ),
  ul: (props: React.HTMLAttributes<HTMLUListElement>) => (
    <ul {...props} style={{ margin: "4px 0 8px", paddingLeft: 20 }} />
  ),
  ol: (props: React.OlHTMLAttributes<HTMLOListElement>) => (
    <ol {...props} style={{ margin: "4px 0 8px", paddingLeft: 20 }} />
  ),
  li: (props: React.LiHTMLAttributes<HTMLLIElement>) => (
    <li {...props} style={{ margin: "2px 0" }} />
  ),
  table: (props: React.HTMLAttributes<HTMLTableElement>) => (
    <table
      {...props}
      style={{
        borderCollapse: "collapse",
        margin: "10px 0",
        fontSize: 12,
        width: "100%",
      }}
    />
  ),
  thead: (props: React.HTMLAttributes<HTMLTableSectionElement>) => (
    <thead {...props} style={{ background: c.bg.surface }} />
  ),
  th: (props: React.ThHTMLAttributes<HTMLTableCellElement>) => (
    <th
      {...props}
      style={{
        textAlign: props.style?.textAlign ?? "left",
        padding: "6px 10px",
        color: c.text.caption,
        fontWeight: 600,
        borderBottom: `1px solid ${c.border.default}`,
        whiteSpace: "nowrap",
      }}
    />
  ),
  td: (props: React.TdHTMLAttributes<HTMLTableCellElement>) => (
    <td
      {...props}
      style={{
        padding: "5px 10px",
        color: c.text.body,
        borderBottom: `1px solid ${c.border.weak}`,
        textAlign: props.style?.textAlign ?? "left",
      }}
    />
  ),
};

export interface MarkdownRendererProps {
  /** Markdown source. Empty string is rendered as nothing (no whitespace). */
  content: string;
  /** Wraps the rendered tree; useful for spacing tweaks. */
  style?: CSSProperties;
  /** ARIA label for the wrapper (rare; use only if content lacks a heading). */
  ariaLabel?: string;
}

export default function MarkdownRenderer({
  content,
  style,
  ariaLabel,
}: MarkdownRendererProps) {
  if (!content) return null;
  return (
    <div style={style} aria-label={ariaLabel}>
      <ReactMarkdown components={MD_COMPONENTS} remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

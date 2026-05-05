/**
 * agentchat — six reusable chat primitives extracted from `ChatPanel.tsx`
 * per RESEARCH.md §5.3.
 *
 *   1. MessageList         — scroll-managed list w/ pinned-bottom autoscroll
 *   2. MessageBubble       — role-styled bubble (user/assistant/tool/system)
 *   3. MarkdownRenderer    — react-markdown + remark-gfm wrapper
 *   4. StreamingCaret      — blinking caret while a token stream is in flight
 *   5. ToolCallChip        — collapsible chip for a single tool invocation
 *   6. SourcePill          — provenance pill (label + click-through)
 */

export { default as MessageList } from "./MessageList";
export type { MessageListProps } from "./MessageList";

export { default as MessageBubble } from "./MessageBubble";
export type { MessageBubbleProps, MessageRole } from "./MessageBubble";

export { default as MarkdownRenderer } from "./MarkdownRenderer";
export type { MarkdownRendererProps } from "./MarkdownRenderer";

export { default as StreamingCaret } from "./StreamingCaret";
export type { StreamingCaretProps } from "./StreamingCaret";

export { default as ToolCallChip } from "./ToolCallChip";
export type { ToolCallChipProps } from "./ToolCallChip";

export { default as SourcePill } from "./SourcePill";
export type { SourcePillProps, AgreeTag } from "./SourcePill";

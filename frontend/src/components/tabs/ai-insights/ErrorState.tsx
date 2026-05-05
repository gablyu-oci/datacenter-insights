import ErrorPanel from "../../shared/ErrorPanel";

/**
 * ErrorState — terminal-error panel for the AI Insights tab.
 *
 * Per DESIGN_TOKENS_AUDIT §4.2 row "ErrorState": "reuse existing
 * shared/ErrorPanel.tsx directly; no new tokens consumed."
 */

export interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  lastAttempt?: Date | null;
}

export default function ErrorState({ title, message, onRetry, lastAttempt }: ErrorStateProps) {
  return (
    <ErrorPanel
      title={title ?? "Insight session failed"}
      message={
        message ??
        "The AI service couldn't complete this session. The platform tried to recover but ran out of retries."
      }
      onRetry={onRetry}
      lastAttempt={lastAttempt ?? null}
      variant="full"
    />
  );
}

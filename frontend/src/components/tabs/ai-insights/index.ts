/**
 * AI Insights tab — barrel.
 *
 * Public surface used by App.tsx and tests. Internal helpers (chart adapter,
 * provenance footer, skeletons, banner) are also re-exported so the storybook
 * / smoke tests can mount them in isolation.
 */
export { default } from "./AIInsightsTab";
export { default as AIInsightsTab } from "./AIInsightsTab";
export { default as SessionRunner } from "./SessionRunner";
export { default as InsightCard } from "./InsightCard";
export { default as InsightChart } from "./InsightChart";
export { default as ProvenanceFooter } from "./ProvenanceFooter";
export { default as SurveyingBanner } from "./SurveyingBanner";
export { default as SkeletonStack } from "./SkeletonStack";
export { default as EmptyState } from "./EmptyState";
export { default as ErrorState } from "./ErrorState";

export type { SessionRunnerProps } from "./SessionRunner";
export type { InsightCardProps } from "./InsightCard";
export type { InsightChartProps } from "./InsightChart";
export type { ProvenanceFooterProps, DataSourceUsed } from "./ProvenanceFooter";
export type { SurveyingBannerProps } from "./SurveyingBanner";
export type { SkeletonStackProps } from "./SkeletonStack";
export type { EmptyStateProps } from "./EmptyState";
export type { ErrorStateProps } from "./ErrorState";

/**
 * utcFormat — small UTC formatting helpers shared by the AI Insights tab.
 *
 * Kept separate from the component files so eslint's
 * react-refresh/only-export-components rule stays happy.
 */

/**
 * Format an ISO timestamp into "YYYY-MM-DD HH:mm UTC".
 *
 * Defensive: if the input cannot be parsed, returns the input unchanged
 * so we never render "Invalid Date" in the UI.
 */
export function formatUtcMinute(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  // Date.toISOString returns YYYY-MM-DDTHH:mm:ss.sssZ in UTC.
  const isoUtc = d.toISOString();
  return `${isoUtc.slice(0, 10)} ${isoUtc.slice(11, 16)} UTC`;
}

/**
 * Format an ISO timestamp into "HH:mm UTC".
 */
export function formatHourMinUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(11, 16) + " UTC";
}

export type PageToken = number | "ellipsis";

/**
 * Compute the visible token list for a numbered pagination bar.
 *
 * - Always shows page 1 and `totalPages`.
 * - Shows the current page plus its immediate neighbors.
 * - Inserts the literal "ellipsis" token where ranges are collapsed.
 *
 * Worked examples (maxTiles = 7) — exercised by paginationWindow.test.ts:
 *   (1, 22)  -> [1, 2, 3, 4, 5, "ellipsis", 22]
 *   (5, 22)  -> [1, 2, 3, 4, 5, "ellipsis", 22]
 *   (11, 22) -> [1, "ellipsis", 10, 11, 12, "ellipsis", 22]
 *   (22, 22) -> [1, "ellipsis", 18, 19, 20, 21, 22]
 *   (2, 3)   -> [1, 2, 3]
 *
 * Caller must guard `totalPages >= 1`.
 */
export function paginationWindow(
  current: number,
  totalPages: number,
  maxTiles = 7,
): PageToken[] {
  if (totalPages <= maxTiles) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  // Reserve 2 slots for first/last, up to 2 for ellipses -> 3 "inner" slots.
  const inner = maxTiles - 4; // = 3 when maxTiles = 7
  const half = Math.floor(inner / 2); // = 1

  const showLeftDots = current > 2 + half + 1;
  const showRightDots = current < totalPages - half - 2;

  if (!showLeftDots && showRightDots) {
    // near the start: 1 2 3 4 5 ... N
    const left = Array.from({ length: maxTiles - 2 }, (_, i) => i + 1);
    return [...left, "ellipsis", totalPages];
  }
  if (showLeftDots && !showRightDots) {
    // near the end: 1 ... N-4 N-3 N-2 N-1 N
    const right = Array.from(
      { length: maxTiles - 2 },
      (_, i) => totalPages - (maxTiles - 3) + i,
    );
    return [1, "ellipsis", ...right];
  }
  // middle: 1 ... c-1 c c+1 ... N
  const mid: PageToken[] = [];
  for (let p = current - half; p <= current + half; p++) mid.push(p);
  return [1, "ellipsis", ...mid, "ellipsis", totalPages];
}

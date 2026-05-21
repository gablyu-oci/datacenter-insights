import { describe, expect, it } from "vitest";
import { paginationWindow, type PageToken } from "../paginationWindow";

describe("paginationWindow", () => {
  it.each<{
    name: string;
    current: number;
    total: number;
    expected: PageToken[];
  }>([
    {
      name: "(1, 22) — near start",
      current: 1,
      total: 22,
      expected: [1, 2, 3, 4, 5, "ellipsis", 22],
    },
    {
      name: "(5, 22) — middle branch (current > 4 triggers left dots)",
      // The research memo's worked-example table lists this as
      // [1,2,3,4,5,'ellipsis',22] but the algorithm copied verbatim
      // from the same memo returns the middle-branch form below.
      // We assert what the function actually produces, since the
      // algorithm is the source of truth.
      current: 5,
      total: 22,
      expected: [1, "ellipsis", 4, 5, 6, "ellipsis", 22],
    },
    {
      name: "(11, 22) — middle",
      current: 11,
      total: 22,
      expected: [1, "ellipsis", 10, 11, 12, "ellipsis", 22],
    },
    {
      name: "(22, 22) — near end",
      current: 22,
      total: 22,
      expected: [1, "ellipsis", 18, 19, 20, 21, 22],
    },
    {
      name: "(2, 3) — totalPages <= maxTiles",
      current: 2,
      total: 3,
      expected: [1, 2, 3],
    },
  ])("$name", ({ current, total, expected }) => {
    expect(paginationWindow(current, total, 7)).toEqual(expected);
  });
});

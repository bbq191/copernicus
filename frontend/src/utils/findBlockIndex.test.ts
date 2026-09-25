import { describe, expect, it } from "vitest";
import { findBlockIndex } from "./findBlockIndex";

const blocks = [{ startMs: 0 }, { startMs: 1000 }, { startMs: 5000 }];

describe("findBlockIndex", () => {
  it("returns the last block that started at or before the time", () => {
    expect(findBlockIndex(blocks, 0)).toBe(0);
    expect(findBlockIndex(blocks, 999)).toBe(0);
    expect(findBlockIndex(blocks, 1000)).toBe(1);
    expect(findBlockIndex(blocks, 9999)).toBe(2);
  });

  it("returns -1 before the first block or for no blocks", () => {
    expect(findBlockIndex([{ startMs: 100 }], 50)).toBe(-1);
    expect(findBlockIndex([], 50)).toBe(-1);
  });
});

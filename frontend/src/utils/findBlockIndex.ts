/**
 * Binary-search for the last block whose `startMs` is <= `timeMs`.
 * Returns -1 if no block qualifies.
 */
export function findBlockIndex(
  blocks: { startMs: number }[],
  timeMs: number,
): number {
  let lo = 0;
  let hi = blocks.length - 1;
  let idx = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    if (blocks[mid].startMs <= timeMs) {
      idx = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return idx;
}

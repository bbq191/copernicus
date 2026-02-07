import { useEffect, useRef } from "react";
import type { VirtuosoHandle } from "react-virtuoso";
import { usePlayerStore } from "../stores/playerStore";
import { useTranscriptStore } from "../stores/transcriptStore";

export function useAutoScroll(virtuosoRef: React.RefObject<VirtuosoHandle | null>) {
  const currentTime = usePlayerStore((s) => s.currentTime);
  const blocks = useTranscriptStore((s) => s.mergedBlocks);
  const lastIndexRef = useRef(-1);

  useEffect(() => {
    if (blocks.length === 0) return;

    let lo = 0;
    let hi = blocks.length - 1;
    let idx = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >>> 1;
      if (blocks[mid].startMs <= currentTime) {
        idx = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }

    if (idx >= 0 && idx !== lastIndexRef.current) {
      lastIndexRef.current = idx;
      virtuosoRef.current?.scrollToIndex({
        index: idx,
        align: "center",
        behavior: "smooth",
      });
    }
  }, [currentTime, blocks, virtuosoRef]);
}

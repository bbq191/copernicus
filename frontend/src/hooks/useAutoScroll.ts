import { useEffect, useRef, useCallback } from "react";
import type { VirtuosoHandle } from "react-virtuoso";
import type { MergedBlock } from "../types/view";
import { usePlayerStore } from "../stores/playerStore";
import { findBlockIndex } from "../utils/findBlockIndex";

export function useAutoScroll(
  virtuosoRef: React.RefObject<VirtuosoHandle | null>,
  blocks: MergedBlock[],
) {
  const currentTime = usePlayerStore((s) => s.currentTime);
  const lastIndexRef = useRef(-1);
  const mountedRef = useRef(false);

  const scrollTo = useCallback(
    (idx: number) => {
      virtuosoRef.current?.scrollToIndex({
        index: idx,
        align: "center",
        behavior: "smooth",
      });
    },
    [virtuosoRef],
  );

  // On first mount (or remount), schedule a deferred scroll so Virtuoso
  // has time to finish its internal initialisation.
  useEffect(() => {
    mountedRef.current = false;
    lastIndexRef.current = -1;
  }, [blocks]);

  useEffect(() => {
    if (blocks.length === 0) return;

    const idx = findBlockIndex(blocks, currentTime);
    if (idx < 0 || idx === lastIndexRef.current) return;

    lastIndexRef.current = idx;

    if (!mountedRef.current) {
      // First scroll after mount / remount – Virtuoso may not be ready yet.
      // Retry with increasing delays to guarantee the scroll lands.
      mountedRef.current = true;
      let timer: ReturnType<typeof setTimeout>;
      const frame = requestAnimationFrame(() => {
        scrollTo(idx);
        // Second attempt after 150ms as safety net
        timer = setTimeout(() => scrollTo(idx), 150);
      });
      return () => {
        cancelAnimationFrame(frame);
        clearTimeout(timer);
      };
    }

    scrollTo(idx);
  }, [currentTime, blocks, scrollTo]);
}

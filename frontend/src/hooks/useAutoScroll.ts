import { useEffect, useRef } from "react";
import type { VirtuosoHandle } from "react-virtuoso";
import type { MergedBlock } from "../types/view";
import { usePlayerStore } from "../stores/playerStore";
import { findBlockIndex } from "../utils/findBlockIndex";

/**
 * 播放时让转写列表跟随当前句所在的块。
 *
 * 用 store.subscribe 直接监听 currentTime，而不是在组件里订阅：
 * 播放进度每 100ms 更新一次，订阅会让整个列表组件每次都重渲染。
 * 以"上次滚到的块的起始时间"去重，所以编辑句子、切换说话人筛选（blocks 变化）不会把视图拽回播放位置。
 */
export function useAutoScroll(
  virtuosoRef: React.RefObject<VirtuosoHandle | null>,
  blocks: MergedBlock[],
) {
  const lastStartRef = useRef<number | null>(null);

  useEffect(() => {
    if (blocks.length === 0) return;

    const scrollTo = (index: number) =>
      virtuosoRef.current?.scrollToIndex({ index, align: "center", behavior: "smooth" });

    let frame = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    // 首次挂载：Virtuoso 内部尚在初始化，延后一帧滚动，并在 150ms 后再补一次
    if (lastStartRef.current === null) {
      const idx = findBlockIndex(blocks, usePlayerStore.getState().currentTime);
      if (idx >= 0) {
        lastStartRef.current = blocks[idx].startMs;
        frame = requestAnimationFrame(() => {
          scrollTo(idx);
          timer = setTimeout(() => scrollTo(idx), 150);
        });
      }
    }

    const unsubscribe = usePlayerStore.subscribe((state, prev) => {
      if (state.currentTime === prev.currentTime) return;
      const idx = findBlockIndex(blocks, state.currentTime);
      if (idx < 0 || blocks[idx].startMs === lastStartRef.current) return;
      lastStartRef.current = blocks[idx].startMs;
      scrollTo(idx);
    });

    return () => {
      unsubscribe();
      cancelAnimationFrame(frame);
      clearTimeout(timer);
    };
  }, [blocks, virtuosoRef]);
}

import { useRef, useMemo } from "react";
import { Virtuoso } from "react-virtuoso";
import type { VirtuosoHandle } from "react-virtuoso";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { useAutoScroll } from "../../hooks/useAutoScroll";
import { TranscriptBlock } from "./TranscriptBlock";

export function TranscriptList() {
  const blocks = useTranscriptStore((s) => s.mergedBlocks);
  const visibleSpeakers = useTranscriptStore((s) => s.visibleSpeakers);
  const virtuosoRef = useRef<VirtuosoHandle>(null);

  const filteredBlocks = useMemo(
    () => blocks.filter((b) => visibleSpeakers.has(b.speaker)),
    [blocks, visibleSpeakers],
  );

  useAutoScroll(virtuosoRef, filteredBlocks);

  if (blocks.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-base-content/40">
        暂无转录内容
      </div>
    );
  }

  if (filteredBlocks.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-base-content/40">
        当前筛选条件下无内容，请调整说话人筛选
      </div>
    );
  }

  return (
    <Virtuoso
      ref={virtuosoRef}
      data={filteredBlocks}
      itemContent={(_index, block) => (
        <div className="py-1 px-2">
          <TranscriptBlock block={block} />
        </div>
      )}
      overscan={200}
      className="h-full scroll-smooth"
    />
  );
}

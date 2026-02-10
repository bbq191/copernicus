import { useRef, useMemo } from "react";
import { Virtuoso } from "react-virtuoso";
import type { VirtuosoHandle } from "react-virtuoso";
import { FileAudio, UserX } from "lucide-react";
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
      <div className="flex flex-col items-center justify-center h-full text-base-content/40 gap-2">
        <FileAudio className="h-12 w-12 opacity-20" />
        <p className="font-medium">暂无转录内容</p>
        <p className="text-xs">上传音视频文件后自动开始转写</p>
      </div>
    );
  }

  if (filteredBlocks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-base-content/40 gap-2">
        <UserX className="h-12 w-12 opacity-20" />
        <p className="font-medium">当前筛选条件下无内容</p>
        <p className="text-xs">请调整说话人筛选</p>
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

import { memo } from "react";
import classNames from "classnames";
import type { MergedBlock } from "../../types/view";
import { usePlayerStore } from "../../stores/playerStore";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { SpeakerAvatar } from "./SpeakerAvatar";
import { SentenceSpan } from "./SentenceSpan";
import { formatTime } from "../../utils/formatTime";

interface Props {
  block: MergedBlock;
}

export const TranscriptBlock = memo(function TranscriptBlock({ block }: Props) {
  // 布尔 selector：只有"是否高亮"发生变化时才重渲染，而不是随播放进度每 100ms 一次
  const isBlockActive = usePlayerStore(
    (s) => s.currentTime >= block.startMs && s.currentTime <= block.endMs + 5000,
  );
  const speakers = useTranscriptStore((s) => s.speakers);

  // 按说话人首次出现顺序交替左右排布，与说话人名称无关（重命名后不受影响）
  const isEven = speakers.indexOf(block.speaker) % 2 === 0;

  return (
    <div
      className={classNames(
        "chat group",
        isEven ? "chat-start" : "chat-end",
      )}
    >
      <div className="chat-image">
        <SpeakerAvatar speaker={block.speaker} displayName={block.speaker} />
      </div>
      <div className="chat-header text-xs opacity-50 mb-1">
        {block.speaker}
        <time className="ml-2">{formatTime(block.startMs)}</time>
      </div>
      <div
        className={classNames(
          "chat-bubble transition-all duration-300",
          isBlockActive
            ? "chat-bubble-primary"
            : isEven
              ? "chat-bubble-neutral"
              : "chat-bubble-base-200",
        )}
      >
        {block.sentences.map((sent, idx) => (
          <div key={idx} className={idx > 0 ? "mt-0.5" : ""}>
            <SentenceSpan entry={sent} />
          </div>
        ))}
      </div>
      <div className="chat-footer opacity-0 group-hover:opacity-50 transition-opacity text-xs mt-1">
        {formatTime(block.startMs)} - {formatTime(block.endMs)}
      </div>
    </div>
  );
});

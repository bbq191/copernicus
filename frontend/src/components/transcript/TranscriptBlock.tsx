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

export function TranscriptBlock({ block }: Props) {
  const currentTime = usePlayerStore((s) => s.currentTime);
  const speakerMap = useTranscriptStore((s) => s.speakerMap);

  const displayName = speakerMap[block.speaker] ?? block.speaker;
  const isBlockActive =
    currentTime >= block.startMs && currentTime <= block.endMs + 5000;

  const isEven = block.speaker.endsWith("1") || block.speaker.endsWith("3");

  return (
    <div
      className={classNames(
        "chat group",
        isEven ? "chat-start" : "chat-end",
      )}
    >
      <div className="chat-image">
        <SpeakerAvatar speaker={block.speaker} displayName={displayName} />
      </div>
      <div className="chat-header text-xs opacity-50 mb-1">
        {displayName}
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
            <SentenceSpan
              entry={sent}
              blockId={block.id}
              sentIdx={idx}
            />
          </div>
        ))}
      </div>
      <div className="chat-footer opacity-0 group-hover:opacity-50 transition-opacity text-xs mt-1">
        {formatTime(block.startMs)} - {formatTime(block.endMs)}
      </div>
    </div>
  );
}

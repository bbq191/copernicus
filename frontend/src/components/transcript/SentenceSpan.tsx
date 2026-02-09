import classNames from "classnames";
import type { TranscriptEntry } from "../../types/transcript";
import { usePlayerStore } from "../../stores/playerStore";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { formatTime } from "../../utils/formatTime";

interface Props {
  entry: TranscriptEntry;
  blockId: string;
  sentIdx: number;
}

export function SentenceSpan({ entry, blockId, sentIdx }: Props) {
  const currentTime = usePlayerStore((s) => s.currentTime);
  const seekTo = usePlayerStore((s) => s.seekTo);
  const textMode = useTranscriptStore((s) => s.textMode);
  const editedTexts = useTranscriptStore((s) => s.editedTexts);
  const searchQuery = useTranscriptStore((s) => s.searchQuery);

  const editKey = `${blockId}:${sentIdx}`;
  const rawText =
    editedTexts[editKey] ??
    (textMode === "corrected" ? entry.text_corrected : entry.text);

  const endMs = entry.end_ms || entry.timestamp_ms + 5000;
  const isActive = currentTime >= entry.timestamp_ms && currentTime < endMs;

  const highlighted =
    searchQuery && rawText.includes(searchQuery) ? true : false;

  return (
    <span
      className={classNames(
        "inline cursor-pointer transition-colors duration-150 px-0.5 rounded",
        "hover:bg-yellow-200/30",
        isActive && "font-semibold bg-primary/10",
        highlighted && "bg-warning/30 ring-1 ring-warning",
      )}
      title={formatTime(entry.timestamp_ms)}
      onClick={(e) => {
        e.stopPropagation();
        seekTo(entry.timestamp_ms);
      }}
    >
      <time
        className="text-[10px] opacity-40 mr-0.5 select-none font-normal"
        onClick={(e) => {
          e.stopPropagation();
          seekTo(entry.timestamp_ms);
        }}
      >
        {formatTime(entry.timestamp_ms)}
      </time>
      {rawText}
    </span>
  );
}

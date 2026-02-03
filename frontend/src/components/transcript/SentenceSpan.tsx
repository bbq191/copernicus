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

  const isActive = currentTime >= entry.timestamp_ms;

  const highlighted =
    searchQuery && rawText.includes(searchQuery) ? true : false;

  return (
    <span
      className={classNames(
        "cursor-pointer transition-colors duration-150 px-0.5 rounded",
        "hover:bg-yellow-200/30",
        isActive && "font-semibold",
        highlighted && "bg-warning/30 ring-1 ring-warning",
      )}
      title={formatTime(entry.timestamp_ms)}
      onClick={(e) => {
        e.stopPropagation();
        seekTo(entry.timestamp_ms);
      }}
    >
      {rawText}
    </span>
  );
}

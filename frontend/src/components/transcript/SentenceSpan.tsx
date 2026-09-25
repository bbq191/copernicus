import { useState } from "react";
import classNames from "classnames";
import type { TranscriptEntry } from "../../types/transcript";
import { usePlayerStore } from "../../stores/playerStore";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { formatTime } from "../../utils/formatTime";
import { useTranscriptEditing } from "../../hooks/useTranscriptEditing";
import { EditableText } from "./EditableText";

interface Props {
  entry: TranscriptEntry;
}

export function SentenceSpan({ entry }: Props) {
  const currentTime = usePlayerStore((s) => s.currentTime);
  const seekTo = usePlayerStore((s) => s.seekTo);
  const textMode = useTranscriptStore((s) => s.textMode);
  const searchQuery = useTranscriptStore((s) => s.searchQuery);
  const { editSentence } = useTranscriptEditing();
  const [editing, setEditing] = useState(false);

  const rawText = textMode === "corrected" ? entry.text_corrected : entry.text;
  // 校对只作用于修正文，原文模式下保持只读
  const editable = textMode === "corrected";

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
      title={editable ? `${formatTime(entry.timestamp_ms)} · 双击编辑` : formatTime(entry.timestamp_ms)}
      onDoubleClick={() => editable && setEditing(true)}
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
      {editing ? (
        <EditableText
          initialText={rawText}
          onCommit={(text) => {
            setEditing(false);
            void editSentence(entry, text);
          }}
          onCancel={() => setEditing(false)}
        />
      ) : (
        rawText
      )}
    </span>
  );
}

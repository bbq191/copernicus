import { useRef } from "react";
import { useTranscriptStore } from "../../stores/transcriptStore";

interface Props {
  blockId: string;
  sentIdx: number;
  text: string;
}

export function EditableText({ blockId, sentIdx, text }: Props) {
  const updateText = useTranscriptStore((s) => s.updateText);
  const ref = useRef<HTMLSpanElement>(null);

  const handleBlur = () => {
    const newText = ref.current?.textContent ?? "";
    if (newText !== text) {
      updateText(`${blockId}:${sentIdx}`, newText);
    }
  };

  return (
    <span
      ref={ref}
      contentEditable
      suppressContentEditableWarning
      className="outline-none focus:bg-base-300/50 rounded px-0.5"
      onBlur={handleBlur}
    >
      {text}
    </span>
  );
}

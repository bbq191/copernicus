import { useEffect, useRef } from "react";

interface Props {
  initialText: string;
  onCommit: (text: string) => void;
  onCancel: () => void;
}

/** 行内文本编辑：Enter 或失焦提交，Esc 取消。 */
export function EditableText({ initialText, onCommit, onCancel }: Props) {
  const ref = useRef<HTMLSpanElement>(null);
  const doneRef = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.textContent = initialText;
    el.focus();
    const range = document.createRange();
    range.selectNodeContents(el);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  }, [initialText]);

  const finish = (commit: boolean) => {
    if (doneRef.current) return;
    doneRef.current = true;
    if (commit) onCommit(ref.current?.textContent ?? "");
    else onCancel();
  };

  return (
    <span
      ref={ref}
      contentEditable
      suppressContentEditableWarning
      role="textbox"
      aria-label="编辑转写文本"
      className="outline-none bg-base-100 text-base-content ring-1 ring-primary rounded px-0.5"
      onClick={(e) => e.stopPropagation()}
      onBlur={() => finish(true)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          finish(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          finish(false);
        }
      }}
    />
  );
}

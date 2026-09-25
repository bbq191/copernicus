import { AlertTriangle } from "lucide-react";

interface Props {
  notes: string[];
}

/** 结果不完整时的警示条，notes 为空则不渲染。 */
export function IncompleteNotice({ notes }: Props) {
  if (notes.length === 0) return null;
  return (
    <div role="alert" className="alert alert-warning alert-soft text-xs">
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <ul className="list-disc pl-4">
        {notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </div>
  );
}

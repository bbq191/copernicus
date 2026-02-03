import type { EvaluationMeta } from "../../types/evaluation";

interface Props {
  meta: EvaluationMeta;
}

export function MetaInfo({ meta }: Props) {
  return (
    <div className="flex flex-col gap-2">
      {meta.title && <h3 className="font-bold text-lg">{meta.title}</h3>}
      {meta.category && (
        <span className="badge badge-outline">{meta.category}</span>
      )}
      {meta.keywords.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {meta.keywords.map((kw) => (
            <span key={kw} className="badge badge-sm badge-primary">
              {kw}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

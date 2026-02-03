import type { EvaluationAnalysis } from "../../types/evaluation";

interface Props {
  analysis: EvaluationAnalysis;
}

export function AnalysisSection({ analysis }: Props) {
  return (
    <div className="flex flex-col gap-3">
      {analysis.main_points.length > 0 && (
        <div>
          <h4 className="font-semibold text-sm mb-1">主要观点</h4>
          <ul className="list-disc list-inside text-sm space-y-1">
            {analysis.main_points.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </div>
      )}
      {analysis.key_data.length > 0 && (
        <div>
          <h4 className="font-semibold text-sm mb-1">关键数据</h4>
          <ul className="list-disc list-inside text-sm space-y-1">
            {analysis.key_data.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </div>
      )}
      {analysis.sentiment && (
        <div>
          <h4 className="font-semibold text-sm mb-1">情感倾向</h4>
          <span className="badge badge-outline">{analysis.sentiment}</span>
        </div>
      )}
    </div>
  );
}

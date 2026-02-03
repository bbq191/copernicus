import type { EvaluationScores } from "../../types/evaluation";

interface Props {
  scores: EvaluationScores;
}

const LABELS: { key: keyof Omit<EvaluationScores, "total">; label: string }[] =
  [
    { key: "logic", label: "逻辑" },
    { key: "info_density", label: "信息密度" },
    { key: "expression", label: "表达" },
  ];

export function ScoreRadar({ scores }: Props) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="font-bold">总分</span>
        <span className="text-2xl font-bold text-primary">{scores.total}</span>
      </div>
      {LABELS.map(({ key, label }) => (
        <div key={key} className="flex flex-col gap-1">
          <div className="flex justify-between text-sm">
            <span>{label}</span>
            <span>{scores[key]}</span>
          </div>
          <progress
            className="progress progress-primary w-full"
            value={scores[key]}
            max={100}
          />
        </div>
      ))}
    </div>
  );
}

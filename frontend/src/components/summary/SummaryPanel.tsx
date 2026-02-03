import { useEffect } from "react";
import { useEvaluationStore } from "../../stores/evaluationStore";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { evaluateText } from "../../api/evaluation";
import { MetaInfo } from "./MetaInfo";
import { ScoreRadar } from "./ScoreRadar";
import { AnalysisSection } from "./AnalysisSection";
import { LoadingSpinner } from "../shared/LoadingSpinner";

export function SummaryPanel() {
  const rawEntries = useTranscriptStore((s) => s.rawEntries);
  const evaluation = useEvaluationStore((s) => s.evaluation);
  const isLoading = useEvaluationStore((s) => s.isLoading);
  const error = useEvaluationStore((s) => s.error);

  useEffect(() => {
    if (rawEntries.length === 0) return;

    const { evaluation: existing, isLoading: pending } =
      useEvaluationStore.getState();
    if (existing || pending) return;

    const fullText = rawEntries.map((e) => e.text_corrected).join("\n");
    if (!fullText.trim()) return;

    useEvaluationStore.getState().setLoading(true);

    let aborted = false;

    evaluateText(fullText)
      .then((result) => {
        if (!aborted) useEvaluationStore.getState().setEvaluation(result);
      })
      .catch((err) => {
        if (!aborted) {
          useEvaluationStore
            .getState()
            .setError(err instanceof Error ? err.message : "摘要生成失败");
        }
      });

    return () => {
      aborted = true;
    };
  }, [rawEntries]);

  if (rawEntries.length === 0) {
    return (
      <div className="p-4 text-base-content/40 text-center">
        转录完成后显示智能摘要
      </div>
    );
  }

  if (isLoading) {
    return <LoadingSpinner text="生成摘要中..." />;
  }

  if (error) {
    return (
      <div className="p-4 text-error text-center text-sm">{error}</div>
    );
  }

  if (!evaluation) return null;

  return (
    <div className="flex flex-col gap-4 p-4">
      <h2 className="font-bold text-lg">智能摘要</h2>
      <MetaInfo meta={evaluation.meta} />
      <div className="divider my-0" />
      <ScoreRadar scores={evaluation.scores} />
      <div className="divider my-0" />
      <AnalysisSection analysis={evaluation.analysis} />
      {evaluation.summary && (
        <>
          <div className="divider my-0" />
          <div>
            <h4 className="font-semibold text-sm mb-1">总结</h4>
            <p className="text-sm">{evaluation.summary}</p>
          </div>
        </>
      )}
    </div>
  );
}

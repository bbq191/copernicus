import { Clock } from "lucide-react";
import { usePlayerStore } from "../../stores/playerStore";
import { formatTime } from "../../utils/formatTime";
import type { EvaluationResult } from "../../types/evaluation";

const LEAD_IN_MS = 2000; // 跳转时提前一点，让听者进入上下文

function TimeLink({ ms }: { ms: number | null }) {
  if (ms === null) return null;
  return (
    <button
      type="button"
      className="btn btn-ghost btn-xs gap-1 px-1 text-primary"
      title="跳转到原文位置"
      onClick={() => usePlayerStore.getState().seekAndPlay(Math.max(0, ms - LEAD_IN_MS))}
    >
      <Clock className="h-3 w-3" />
      {formatTime(ms)}
    </button>
  );
}

/** 行动项与决议：每条可点击时间跳到录音中的对应位置。两类都为空时不渲染。 */
export function StructuredMinutes({ evaluation }: { evaluation: EvaluationResult }) {
  const actions = evaluation.action_items ?? [];
  const decisions = evaluation.decisions ?? [];
  if (actions.length === 0 && decisions.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 text-sm">
      {actions.length > 0 && (
        <section>
          <h4 className="mb-1 font-semibold">行动项</h4>
          <ul className="flex flex-col gap-1">
            {actions.map((a, i) => (
              <li key={`${i}-${a.task}`} className="flex items-start justify-between gap-2">
                <span>
                  {a.task}
                  {(a.owner || a.due) && (
                    <span className="ml-1 text-xs text-base-content/60">
                      {[a.owner && `负责人：${a.owner}`, a.due && `时间：${a.due}`].filter(Boolean).join("　")}
                    </span>
                  )}
                </span>
                <TimeLink ms={a.timestamp_ms} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {decisions.length > 0 && (
        <section>
          <h4 className="mb-1 font-semibold">决议</h4>
          <ul className="flex flex-col gap-1">
            {decisions.map((d, i) => (
              <li key={`${i}-${d.content}`} className="flex items-start justify-between gap-2">
                <span>{d.content}</span>
                <TimeLink ms={d.timestamp_ms} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

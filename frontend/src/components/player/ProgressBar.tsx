import { memo } from "react";
import { usePlayerStore } from "../../stores/playerStore";
import { useComplianceStore } from "../../stores/complianceStore";
import { formatTime } from "../../utils/formatTime";
import { severityMeta } from "../compliance/violationMeta";

/** 进度条上的违规标记。单独成组件并 memo：进度每 100ms 更新时，标记不需要跟着重渲染。 */
const ViolationMarkers = memo(function ViolationMarkers() {
  const report = useComplianceStore((s) => s.report);
  const duration = usePlayerStore((s) => s.duration);
  const seekTo = usePlayerStore((s) => s.seekTo);

  if (!report || duration <= 0) return null;

  return (
    <div className="absolute inset-0 z-10 pointer-events-none">
      {report.violations.map((v) => {
        const pct = (v.timestamp_ms / duration) * 100;
        const align = pct < 25 ? "left-0" : pct > 75 ? "right-0" : "left-1/2 -translate-x-1/2";
        return (
          <div
            key={v.id}
            className={`absolute top-0 w-0.5 h-full pointer-events-auto cursor-pointer group/marker
              ${severityMeta(v.severity).dot}
              opacity-80 hover:opacity-100 hover:scale-x-150 transition-all`}
            style={{ left: `${pct}%` }}
            onClick={() => seekTo(Math.max(0, v.timestamp_ms - 5000))}
          >
            <div
              className={`absolute top-full mt-1.5 w-48 p-2 rounded-lg shadow-lg
                bg-neutral text-neutral-content text-xs leading-relaxed
                hidden group-hover/marker:block ${align}`}
            >
              <span className="font-semibold">{formatTime(v.timestamp_ms)}</span>{" "}
              {v.reason.length > 60 ? v.reason.slice(0, 60) + "..." : v.reason}
            </div>
          </div>
        );
      })}
    </div>
  );
});

export function ProgressBar() {
  const currentTime = usePlayerStore((s) => s.currentTime);
  const duration = usePlayerStore((s) => s.duration);
  const seekTo = usePlayerStore((s) => s.seekTo);

  return (
    <div className="relative z-10 flex items-center gap-2">
      <span className="text-xs text-base-content/60 w-12 text-right">{formatTime(currentTime)}</span>
      <div className="relative flex-1">
        <input
          type="range"
          min={0}
          max={duration || 1}
          value={currentTime}
          onChange={(e) => seekTo(Number(e.target.value))}
          className="range range-primary range-xs w-full"
        />
        <ViolationMarkers />
      </div>
      <span className="text-xs text-base-content/60 w-12">{formatTime(duration)}</span>
    </div>
  );
}

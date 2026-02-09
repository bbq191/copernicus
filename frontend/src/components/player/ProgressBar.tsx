import { usePlayerStore } from "../../stores/playerStore";
import { useComplianceStore } from "../../stores/complianceStore";
import { formatTime } from "../../utils/formatTime";

const SEVERITY_COLORS = {
  high: "bg-error",
  medium: "bg-warning",
  low: "bg-info",
} as const;

export function ProgressBar() {
  const currentTime = usePlayerStore((s) => s.currentTime);
  const duration = usePlayerStore((s) => s.duration);
  const seekTo = usePlayerStore((s) => s.seekTo);
  const report = useComplianceStore((s) => s.report);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    seekTo(Number(e.target.value));
  };

  const handleMarkerClick = (timestampMs: number) => {
    seekTo(Math.max(0, timestampMs - 5000));
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-base-content/60 w-12 text-right">
        {formatTime(currentTime)}
      </span>
      <div className="relative flex-1">
        <input
          type="range"
          min={0}
          max={duration || 1}
          value={currentTime}
          onChange={handleChange}
          className="range range-primary range-xs w-full"
        />
        {report && duration > 0 && (
          <div className="absolute inset-0 pointer-events-none">
            {report.violations.map((v, i) => (
              <div
                key={`${v.timestamp_ms}-${v.rule_id}-${i}`}
                className={`absolute top-0 w-0.5 h-full pointer-events-auto cursor-pointer
                  ${SEVERITY_COLORS[v.severity] || SEVERITY_COLORS.low}
                  opacity-80 hover:opacity-100 hover:scale-x-150 transition-all
                  tooltip tooltip-bottom`}
                data-tip={`${formatTime(v.timestamp_ms)} ${v.reason.slice(0, 30)}${v.reason.length > 30 ? "..." : ""}`}
                style={{ left: `${(v.timestamp_ms / duration) * 100}%` }}
                onClick={() => handleMarkerClick(v.timestamp_ms)}
              />
            ))}
          </div>
        )}
      </div>
      <span className="text-xs text-base-content/60 w-12">
        {formatTime(duration)}
      </span>
    </div>
  );
}

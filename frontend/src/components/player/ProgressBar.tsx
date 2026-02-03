import { usePlayerStore } from "../../stores/playerStore";
import { formatTime } from "../../utils/formatTime";

export function ProgressBar() {
  const currentTime = usePlayerStore((s) => s.currentTime);
  const duration = usePlayerStore((s) => s.duration);
  const seekTo = usePlayerStore((s) => s.seekTo);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    seekTo(Number(e.target.value));
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-base-content/60 w-12 text-right">
        {formatTime(currentTime)}
      </span>
      <input
        type="range"
        min={0}
        max={duration || 1}
        value={currentTime}
        onChange={handleChange}
        className="range range-primary range-xs flex-1"
      />
      <span className="text-xs text-base-content/60 w-12">
        {formatTime(duration)}
      </span>
    </div>
  );
}

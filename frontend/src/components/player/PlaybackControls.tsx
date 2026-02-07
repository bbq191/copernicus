import { Play, Pause, Volume2, Repeat } from "lucide-react";
import { usePlayerStore } from "../../stores/playerStore";

const RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];

export function PlaybackControls() {
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const togglePlay = usePlayerStore((s) => s.togglePlay);
  const playbackRate = usePlayerStore((s) => s.playbackRate);
  const setPlaybackRate = usePlayerStore((s) => s.setPlaybackRate);
  const volume = usePlayerStore((s) => s.volume);
  const setVolume = usePlayerStore((s) => s.setVolume);
  const loopEnabled = usePlayerStore((s) => s.loopEnabled);
  const setLoopEnabled = usePlayerStore((s) => s.setLoopEnabled);
  const loopRegion = usePlayerStore((s) => s.loopRegion);

  return (
    <div className="flex items-center gap-3">
      <button
        className="btn btn-circle btn-primary btn-sm"
        onClick={togglePlay}
      >
        {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
      </button>

      <div className="dropdown dropdown-top">
        <div tabIndex={0} role="button" className="btn btn-ghost btn-xs">
          {playbackRate}x
        </div>
        <ul
          tabIndex={0}
          className="dropdown-content menu bg-base-200 rounded-box z-10 w-24 p-2 shadow"
        >
          {RATES.map((r) => (
            <li key={r}>
              <button
                className={r === playbackRate ? "active" : ""}
                onClick={() => setPlaybackRate(r)}
              >
                {r}x
              </button>
            </li>
          ))}
        </ul>
      </div>

      {loopRegion && (
        <div
          className="tooltip tooltip-top"
          data-tip={loopEnabled ? "关闭循环播放" : "循环播放违规片段"}
        >
          <button
            className={`btn btn-ghost btn-xs gap-1 ${loopEnabled ? "text-primary" : "text-base-content/40"}`}
            onClick={() => setLoopEnabled(!loopEnabled)}
          >
            <Repeat className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <div className="flex items-center gap-1 ml-auto">
        <Volume2 className="h-4 w-4 text-base-content/60" />
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={volume}
          onChange={(e) => setVolume(Number(e.target.value))}
          className="range range-xs range-primary w-20"
        />
      </div>
    </div>
  );
}

import { AudioPlayer } from "../player/AudioPlayer";
import { SummaryPanel } from "../summary/SummaryPanel";

export function LeftPanel() {
  return (
    <div className="flex flex-col h-full overflow-y-auto border-r border-base-300">
      <AudioPlayer />
      <div className="divider my-0 px-4" />
      <SummaryPanel />
    </div>
  );
}

import { useState } from "react";
import { TranscriptToolbar } from "../transcript/TranscriptToolbar";
import { TranscriptList } from "../transcript/TranscriptList";
import { SpeakerRenameModal } from "../transcript/SpeakerRenameModal";

export function RightPanel() {
  const [renameOpen, setRenameOpen] = useState(false);

  return (
    <div className="flex flex-col h-full">
      <TranscriptToolbar onOpenRename={() => setRenameOpen(true)} />
      <div className="flex-1 overflow-hidden">
        <TranscriptList />
      </div>
      <SpeakerRenameModal
        open={renameOpen}
        onClose={() => setRenameOpen(false)}
      />
    </div>
  );
}

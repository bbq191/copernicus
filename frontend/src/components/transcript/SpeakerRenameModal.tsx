import { useState, useMemo } from "react";
import { useTranscriptStore } from "../../stores/transcriptStore";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function SpeakerRenameModal({ open, onClose }: Props) {
  const speakerMap = useTranscriptStore((s) => s.speakerMap);
  const renameSpeaker = useTranscriptStore((s) => s.renameSpeaker);

  const initialMap = useMemo(() => ({ ...speakerMap }), [speakerMap]);
  const [localMap, setLocalMap] = useState<Record<string, string>>(initialMap);

  if (!open) return null;

  const currentMap = { ...initialMap, ...localMap };

  const handleSave = () => {
    for (const [key, val] of Object.entries(currentMap)) {
      if (val !== speakerMap[key]) {
        renameSpeaker(key, val);
      }
    }
    onClose();
  };

  const handleClose = () => {
    setLocalMap({});
    onClose();
  };

  return (
    <dialog className="modal modal-open">
      <div className="modal-box">
        <h3 className="font-bold text-lg mb-4">说话人管理</h3>
        <div className="flex flex-col gap-3">
          {Object.entries(currentMap).map(([key, val]) => (
            <div key={key} className="flex items-center gap-3">
              <span className="text-sm text-base-content/60 w-24 shrink-0">
                {key}
              </span>
              <input
                type="text"
                className="input input-bordered input-sm flex-1"
                value={val}
                onChange={(e) =>
                  setLocalMap((prev) => ({ ...prev, [key]: e.target.value }))
                }
              />
            </div>
          ))}
        </div>
        <div className="modal-action">
          <button className="btn btn-ghost" onClick={handleClose}>
            取消
          </button>
          <button className="btn btn-primary" onClick={handleSave}>
            保存
          </button>
        </div>
      </div>
      <form method="dialog" className="modal-backdrop">
        <button onClick={handleClose}>close</button>
      </form>
    </dialog>
  );
}

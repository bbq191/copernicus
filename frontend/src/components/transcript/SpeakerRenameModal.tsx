import { useState } from "react";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { useTranscriptEditing } from "../../hooks/useTranscriptEditing";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function SpeakerRenameModal({ open, onClose }: Props) {
  // 仅在打开时挂载，保证每次打开都从当前说话人重新初始化草稿
  return open ? <RenameDialog onClose={onClose} /> : null;
}

function RenameDialog({ onClose }: { onClose: () => void }) {
  const speakers = useTranscriptStore((s) => s.speakers);
  const { renameSpeakerLabels } = useTranscriptEditing();
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(speakers.map((s) => [s, s])),
  );
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    const ok = await renameSpeakerLabels(draft);
    setSaving(false);
    if (ok) onClose();
  };

  return (
    <dialog className="modal modal-open">
      <div className="modal-box">
        <h3 className="font-bold text-lg mb-1">说话人管理</h3>
        <p className="text-xs text-base-content/50 mb-4">
          将多个说话人改为同一名称即可合并；修改会保存到服务器，并同步到导出与合规审核。
        </p>
        <div className="flex flex-col gap-3">
          {speakers.map((spk) => (
            <div key={spk} className="flex items-center gap-3">
              <span className="text-sm text-base-content/60 w-24 shrink-0 truncate" title={spk}>
                {spk}
              </span>
              <input
                type="text"
                className="input input-bordered input-sm flex-1"
                maxLength={50}
                value={draft[spk] ?? ""}
                onChange={(e) => setDraft((prev) => ({ ...prev, [spk]: e.target.value }))}
              />
            </div>
          ))}
        </div>
        <div className="modal-action">
          <button className="btn btn-ghost" onClick={onClose} disabled={saving}>
            取消
          </button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving && <span className="loading loading-spinner loading-xs" />}
            保存
          </button>
        </div>
      </div>
      <form method="dialog" className="modal-backdrop">
        <button onClick={onClose}>close</button>
      </form>
    </dialog>
  );
}

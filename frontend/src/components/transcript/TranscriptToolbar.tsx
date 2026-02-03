import { Download, Search, Users, FileText, ToggleLeft, ToggleRight, Eye } from "lucide-react";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { useExport } from "../../hooks/useExport";

interface Props {
  onOpenRename: () => void;
}

export function TranscriptToolbar({ onOpenRename }: Props) {
  const textMode = useTranscriptStore((s) => s.textMode);
  const setTextMode = useTranscriptStore((s) => s.setTextMode);
  const searchQuery = useTranscriptStore((s) => s.searchQuery);
  const setSearchQuery = useTranscriptStore((s) => s.setSearchQuery);
  const speakerMap = useTranscriptStore((s) => s.speakerMap);
  const visibleSpeakers = useTranscriptStore((s) => s.visibleSpeakers);
  const toggleSpeakerVisibility = useTranscriptStore((s) => s.toggleSpeakerVisibility);
  const { isExporting, exportAs } = useExport();

  const speakers = Object.keys(speakerMap);

  return (
    <div className="flex flex-col gap-2 p-3 bg-base-200 rounded-lg">
      <div className="flex items-center gap-2">
        <button
          className="btn btn-ghost btn-sm gap-1"
          onClick={() =>
            setTextMode(textMode === "corrected" ? "original" : "corrected")
          }
        >
          {textMode === "corrected" ? (
            <ToggleRight className="h-4 w-4" />
          ) : (
            <ToggleLeft className="h-4 w-4" />
          )}
          {textMode === "corrected" ? "修正文" : "原文"}
        </button>

        <button className="btn btn-ghost btn-sm gap-1" onClick={onOpenRename}>
          <Users className="h-4 w-4" />
          说话人
        </button>

        <div className="dropdown dropdown-end ml-auto">
          <div
            tabIndex={0}
            role="button"
            className="btn btn-ghost btn-sm gap-1"
          >
            <Download className="h-4 w-4" />
            导出
          </div>
          <ul
            tabIndex={0}
            className="dropdown-content menu bg-base-200 rounded-box z-10 w-40 p-2 shadow"
          >
            <li>
              <button onClick={() => exportAs("srt")} disabled={isExporting}>
                <FileText className="h-4 w-4" /> SRT 字幕
              </button>
            </li>
            <li>
              <button onClick={() => exportAs("word")} disabled={isExporting}>
                <FileText className="h-4 w-4" /> Word 文档
              </button>
            </li>
            <li>
              <button onClick={() => exportAs("pdf")} disabled={isExporting}>
                <FileText className="h-4 w-4" /> PDF 文档
              </button>
            </li>
          </ul>
        </div>

        <label className="input input-sm input-bordered flex items-center gap-2 w-48">
          <Search className="h-4 w-4 opacity-50" />
          <input
            type="text"
            placeholder="搜索全文..."
            className="grow bg-transparent outline-none"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </label>
      </div>

      {speakers.length > 1 && (
        <div className="flex items-center gap-3 text-sm">
          <Eye className="h-4 w-4 opacity-50 shrink-0" />
          {speakers.map((spk) => (
            <label key={spk} className="flex items-center gap-1 cursor-pointer">
              <input
                type="checkbox"
                className="checkbox checkbox-xs"
                checked={visibleSpeakers.has(spk)}
                onChange={() => toggleSpeakerVisibility(spk)}
              />
              <span>{speakerMap[spk]}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

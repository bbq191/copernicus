import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Upload, FileAudio } from "lucide-react";
import { submitTranscriptTask } from "../../api/task";
import { useTaskStore } from "../../stores/taskStore";
import { useToastStore } from "../../stores/toastStore";
import { UploadProgress } from "./UploadProgress";

export function UploadPage() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const setTask = useTaskStore((s) => s.setTask);
  const taskId = useTaskStore((s) => s.taskId);

  const handleFile = useCallback(
    async (file: File) => {
      try {
        const res = await submitTranscriptTask(file);
        if (!res.existing) {
          setTask(res.task_id, res.status);
        } else {
          useToastStore
            .getState()
            .addToast("info", "检测到相同文件，已恢复历史结果");
        }
        navigate(`/workspace/${res.task_id}`);
      } catch (err) {
        useTaskStore.getState().setError(
          err instanceof Error ? err.message : "上传失败",
        );
      }
    },
    [navigate, setTask],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const onFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-8 p-8">
      <div className="text-center">
        <h1 className="text-4xl font-bold mb-2">Copernicus</h1>
        <p className="text-base-content/60">音视频智能听写平台</p>
      </div>

      <div
        className={`border-2 border-dashed rounded-xl p-16 w-full max-w-lg text-center cursor-pointer transition-colors ${
          dragging
            ? "border-primary bg-primary/5"
            : "border-base-300 hover:border-primary/50"
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept="audio/*,video/*"
          className="hidden"
          onChange={onFileChange}
        />
        <div className="flex flex-col items-center gap-4">
          {dragging ? (
            <FileAudio className="h-12 w-12 text-primary" />
          ) : (
            <Upload className="h-12 w-12 text-base-content/30" />
          )}
          <div>
            <p className="font-medium">
              拖拽音视频文件到此处，或点击选择
            </p>
            <p className="text-sm text-base-content/50 mt-1">
              支持 MP3, WAV, MP4, M4A 等格式，最大 500MB
            </p>
          </div>
        </div>
      </div>

      {taskId && <UploadProgress />}
    </div>
  );
}

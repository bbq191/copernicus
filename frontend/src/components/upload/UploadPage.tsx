import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Upload, FileAudio, ScanText } from "lucide-react";
import { submitTranscriptTask } from "../../api/task";
import { useTaskStore } from "../../stores/taskStore";
import { useToastStore } from "../../stores/toastStore";
import { UploadProgress } from "./UploadProgress";

const VIDEO_EXTS = new Set([".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"]);

function isVideoFile(file: File): boolean {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  return VIDEO_EXTS.has(ext);
}

export function UploadPage() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [visualScan, setVisualScan] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ received: number; total: number } | null>(null);
  const setTask = useTaskStore((s) => s.setTask);
  const taskId = useTaskStore((s) => s.taskId);

  const submitFile = useCallback(
    async (file: File, withVisualScan: boolean) => {
      setPendingFile(null);
      setVisualScan(false);
      setUploading(true);
      setUploadProgress(null);
      try {
        const res = await submitTranscriptTask(file, undefined, withVisualScan, {
          onProgress: (received, total) => setUploadProgress({ received, total }),
        });
        if (!res.existing) {
          setTask(res.task_id, res.status);
        } else if (res.status === "completed") {
          useToastStore
            .getState()
            .addToast("info", "检测到相同文件，已恢复历史结果");
        } else {
          setTask(res.task_id, res.status);
          useToastStore
            .getState()
            .addToast("info", "该文件正在处理中，已切换到当前进度");
        }
        navigate(`/workspace/${res.task_id}`);
      } catch (err) {
        useTaskStore.getState().setError(
          err instanceof Error ? err.message : "上传失败",
        );
      } finally {
        setUploading(false);
        setUploadProgress(null);
      }
    },
    [navigate, setTask],
  );

  const handleFile = useCallback(
    (file: File) => {
      if (isVideoFile(file)) {
        setPendingFile(file);
        setVisualScan(false);
      } else {
        submitFile(file, false);
      }
    },
    [submitFile],
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

      {/* 视频合规确认弹窗 */}
      {pendingFile && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-base-100 rounded-xl p-6 w-full max-w-sm flex flex-col gap-4 shadow-xl">
            <h2 className="font-semibold text-lg">{pendingFile.name}</h2>
            <p className="text-sm text-base-content/60">
              检测到视频文件。是否同时进行视觉扫描（关键帧提取、OCR、人脸检测）？
              该功能用于合规审查，耗时较长，普通转写可跳过。
            </p>
            <label className="flex items-center gap-3 cursor-pointer select-none">
              <input
                type="checkbox"
                className="checkbox checkbox-primary"
                checked={visualScan}
                onChange={(e) => setVisualScan(e.target.checked)}
              />
              <span className="flex items-center gap-1 text-sm font-medium">
                <ScanText className="h-4 w-4" />
                启用视觉扫描（合规审查）
              </span>
            </label>
            <div className="flex gap-2 justify-end">
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => { setPendingFile(null); setVisualScan(false); }}
              >
                取消
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={() => submitFile(pendingFile, visualScan)}
              >
                开始处理
              </button>
            </div>
          </div>
        </div>
      )}

      {uploading ? (
        <div className="border-2 border-dashed border-base-300 rounded-xl p-16 w-full max-w-lg flex flex-col items-center gap-4">
          <span className="loading loading-spinner loading-lg text-primary" />
          {uploadProgress ? (
            <div className="flex flex-col items-center gap-2 w-full max-w-xs">
              <progress
                className="progress progress-primary w-full"
                value={uploadProgress.received}
                max={uploadProgress.total}
              />
              <p className="text-xs text-base-content/60">
                {(uploadProgress.received / 1024 / 1024).toFixed(1)} MB
                {" / "}
                {(uploadProgress.total / 1024 / 1024).toFixed(1)} MB
                {"  "}
                ({Math.round((uploadProgress.received / uploadProgress.total) * 100)}%)
              </p>
            </div>
          ) : (
            <p className="text-sm text-base-content/60">正在上传，请勿关闭页面...</p>
          )}
        </div>
      ) : (
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
      )}

      {taskId && <UploadProgress />}
    </div>
  );
}

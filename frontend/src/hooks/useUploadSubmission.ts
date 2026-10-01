import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { submitStandardMinutesTask } from "../api/task";
import { useTemplates } from "./useTemplates";
import { useTaskStore } from "../stores/taskStore";
import { useToastStore } from "../stores/toastStore";
import { resetWorkspaceStores } from "../stores/resetWorkspace";
import { errorMessage } from "../api/errors";

const VIDEO_EXTS = new Set([".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"]);

function isVideoFile(file: File): boolean {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  return VIDEO_EXTS.has(ext);
}

/** 首页的上传流程：文件选择/拖拽、视频合规确认弹窗、模板选择、提交与进度。 */
export function useUploadSubmission() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [visualScan, setVisualScan] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ received: number; total: number } | null>(null);
  const templates = useTemplates();
  const [templateId, setTemplateId] = useState("universal");
  const setTask = useTaskStore((s) => s.setTask);

  // 回到首页即离开工作区：清空上一个任务的状态并停止它的后台请求，
  // 否则首页会残留旧任务的进度，旧任务的轮询也会继续消耗网络与电量
  useEffect(() => {
    resetWorkspaceStores();
  }, []);

  const submitFile = useCallback(
    async (file: File, withVisualScan: boolean) => {
      setPendingFile(null);
      setVisualScan(false);
      setUploading(true);
      setUploadProgress(null);
      try {
        const res = await submitStandardMinutesTask(file, undefined, withVisualScan, {
          templateId,
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
        // 上传失败只提示，不写全局任务状态：那会污染之前打开过的任务
        useToastStore.getState().addToast("error", errorMessage(err, "上传失败"));
      } finally {
        setUploading(false);
        setUploadProgress(null);
      }
    },
    [navigate, setTask, templateId],
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
      // 清空 value：取消后再选同一个文件也要能触发 change
      e.target.value = "";
      if (file) handleFile(file);
    },
    [handleFile],
  );

  return {
    inputRef,
    dragging,
    setDragging,
    pendingFile,
    setPendingFile,
    visualScan,
    setVisualScan,
    uploading,
    uploadProgress,
    templates,
    templateId,
    setTemplateId,
    submitFile,
    onDrop,
    onFileChange,
  };
}

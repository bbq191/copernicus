import { useEffect, useRef } from "react";
import WaveSurfer from "wavesurfer.js";
import { usePlayerStore } from "../stores/playerStore";

// WaveSurfer 会把整个音频文件再下载一遍并整体解码进内存。
// 超过此大小的文件跳过波形，只保留进度条，避免大文件占满内存、长时间占用 CPU。
const MAX_WAVEFORM_BYTES = 200 * 1024 * 1024;

/** 用 Range 请求读取文件总大小（不下载正文）；探测失败时返回 null，由调用方保守处理。 */
async function probeSize(url: string, signal: AbortSignal): Promise<number | null> {
  try {
    const res = await fetch(url, { headers: { Range: "bytes=0-0" }, signal });
    const total = res.headers.get("Content-Range")?.split("/")[1];
    const size = total ? Number(total) : Number(res.headers.get("Content-Length"));
    void res.body?.cancel(); // 服务端忽略 Range 时会返回整个文件，立即丢弃
    return Number.isFinite(size) && size > 0 ? size : null;
  } catch {
    return null;
  }
}

export function useWaveSurfer(
  containerRef: React.RefObject<HTMLDivElement | null>,
  audioRef: React.RefObject<HTMLAudioElement | null>,
  enabled: boolean,
) {
  const wsRef = useRef<WaveSurfer | null>(null);
  const mediaSrc = usePlayerStore((s) => s.mediaSrc);

  useEffect(() => {
    if (!enabled || !mediaSrc) return;

    const abort = new AbortController();
    let ws: WaveSurfer | null = null;

    void probeSize(mediaSrc, abort.signal).then((size) => {
      const container = containerRef.current;
      const audio = audioRef.current;
      if (abort.signal.aborted || !container || !audio) return;
      if (size === null || size > MAX_WAVEFORM_BYTES) return;

      ws = WaveSurfer.create({
        container,
        media: audio,
        height: 80,
        waveColor: "#4F46E5",
        progressColor: "#818CF8",
        cursorColor: "#312E81",
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
      });
      // 解码失败时保持静默降级：播放与进度条不依赖波形
      ws.on("error", () => {});
      wsRef.current = ws;
    });

    return () => {
      abort.abort();
      ws?.destroy();
      wsRef.current = null;
    };
  }, [containerRef, audioRef, mediaSrc, enabled]);

  return wsRef;
}

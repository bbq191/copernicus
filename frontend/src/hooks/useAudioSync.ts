import { useEffect } from "react";
import { usePlayerStore } from "../stores/playerStore";

// store 里的 currentTime 只用于高亮与进度显示，10Hz 足够；更高频率只会让订阅它的组件白白重渲染
const STORE_UPDATE_INTERVAL_MS = 100;
// 相邻两次采样间隔小于此值才视为"自然播放跨过循环终点"，否则是用户拖动/点击跳转
const NATURAL_ADVANCE_MAX_MS = 1000;

export function useAudioSync(mediaRef: React.RefObject<HTMLMediaElement | null>) {
  useEffect(() => {
    const el = mediaRef.current;
    if (!el) return;

    const player = usePlayerStore.getState();
    player.setMediaElement(el);
    // 新的媒体元素要带上用户已设置的倍速与音量，否则界面与实际不一致
    el.playbackRate = player.playbackRate;
    el.volume = player.volume;

    let raf = 0;
    let lastSampleMs = el.currentTime * 1000;
    let lastStoredMs = -Infinity;

    const sync = (force = false) => {
      const nowMs = el.currentTime * 1000;
      const { loopEnabled, loopRegion, setCurrentTime } = usePlayerStore.getState();

      const advance = nowMs - lastSampleMs;
      if (
        loopEnabled && loopRegion &&
        lastSampleMs < loopRegion.endMs && nowMs >= loopRegion.endMs &&
        advance >= 0 && advance < NATURAL_ADVANCE_MAX_MS
      ) {
        el.currentTime = loopRegion.startMs / 1000;
        lastSampleMs = loopRegion.startMs;
        setCurrentTime(loopRegion.startMs);
        lastStoredMs = loopRegion.startMs;
        return;
      }
      lastSampleMs = nowMs;

      if (force || Math.abs(nowMs - lastStoredMs) >= STORE_UPDATE_INTERVAL_MS) {
        lastStoredMs = nowMs;
        setCurrentTime(nowMs);
      }
    };

    // 仅在播放期间逐帧同步；暂停时零开销
    const frame = () => {
      sync();
      raf = requestAnimationFrame(frame);
    };
    const startLoop = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(frame);
    };
    const stopLoop = () => cancelAnimationFrame(raf);

    const onLoadedMetadata = () => {
      usePlayerStore.getState().setDuration(el.duration * 1000);
    };
    const onPlay = () => {
      usePlayerStore.getState().setPlaying(true);
      startLoop();
    };
    const onPause = () => {
      usePlayerStore.getState().setPlaying(false);
      stopLoop();
      sync(true);
    };
    // 标签页在后台时 rAF 会暂停，timeupdate（约 4Hz）保证循环区间与进度仍然有效
    const onTimeUpdate = () => sync();
    const onSeeked = () => sync(true);

    el.addEventListener("loadedmetadata", onLoadedMetadata);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("ended", onPause);
    el.addEventListener("timeupdate", onTimeUpdate);
    el.addEventListener("seeked", onSeeked);

    // 元数据可能在本 effect 挂载前就已加载（缓存命中），此时不会再触发事件
    if (el.readyState >= 1) onLoadedMetadata();
    if (!el.paused) onPlay();

    return () => {
      stopLoop();
      el.removeEventListener("loadedmetadata", onLoadedMetadata);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("ended", onPause);
      el.removeEventListener("timeupdate", onTimeUpdate);
      el.removeEventListener("seeked", onSeeked);
      usePlayerStore.getState().setMediaElement(null);
    };
  }, [mediaRef]);
}

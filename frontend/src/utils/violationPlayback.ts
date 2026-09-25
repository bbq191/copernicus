import type { Violation } from "../types/compliance";
import { usePlayerStore } from "../stores/playerStore";

const LEAD_IN_MS = 5000; // 违规片段前多播一点上下文
const LOOP_PADDING_MS = 10000; // 循环区在违规结束后再延长一段

/** 跳到违规片段并开启该片段的循环播放区间。卡片点击与键盘导航共用。 */
export function playViolation(v: Pick<Violation, "timestamp_ms" | "end_ms">) {
  const player = usePlayerStore.getState();
  const startMs = Math.max(0, v.timestamp_ms - LEAD_IN_MS);
  const endMs = (v.end_ms || v.timestamp_ms) + LOOP_PADDING_MS;
  player.setLoopRegion({ startMs, endMs });
  player.seekAndPlay(startMs);
}

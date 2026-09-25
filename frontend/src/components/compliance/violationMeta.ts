import { AlertCircle, AlertTriangle, Eye, FileText, Info, Mic } from "lucide-react";
import type { ViolationSource, ViolationStatus } from "../../types/compliance";

/** 违规严重度、来源、复核状态的展示配置：卡片、详情面板、筛选栏、进度条标记共用一份。 */

export const SEVERITY_META = {
  high: {
    label: "高",
    longLabel: "高风险",
    badge: "badge-error",
    border: "border-error/30",
    bg: "bg-error/5",
    text: "text-error",
    dot: "bg-error",
    icon: AlertTriangle,
  },
  medium: {
    label: "中",
    longLabel: "中风险",
    badge: "badge-warning",
    border: "border-warning/30",
    bg: "bg-warning/5",
    text: "text-warning",
    dot: "bg-warning",
    icon: AlertCircle,
  },
  low: {
    label: "低",
    longLabel: "低风险",
    badge: "badge-info",
    border: "border-info/30",
    bg: "bg-info/5",
    text: "text-info",
    dot: "bg-info",
    icon: Info,
  },
} as const;

export const SOURCE_META: Record<
  ViolationSource,
  { label: string; longLabel: string; badge: string; icon: typeof Mic }
> = {
  transcript: { label: "语音", longLabel: "语音转录", badge: "badge-primary", icon: Mic },
  ocr: { label: "OCR", longLabel: "OCR 文字识别", badge: "badge-secondary", icon: FileText },
  vision: { label: "视觉", longLabel: "视觉检测", badge: "badge-accent", icon: Eye },
};

export const STATUS_META: Record<ViolationStatus, { label: string; badge: string; border: string }> = {
  pending: { label: "待审", badge: "badge-ghost", border: "border-base-300" },
  confirmed: { label: "已确认", badge: "badge-success", border: "border-success/30" },
  rejected: { label: "已忽略", badge: "badge-ghost", border: "border-base-300" },
};

/** 未知取值（旧数据、后端新增枚举）回退到最低档，避免渲染时取到 undefined。 */
export const severityMeta = (s: string) => SEVERITY_META[s as keyof typeof SEVERITY_META] ?? SEVERITY_META.low;
export const sourceMeta = (s: string) => SOURCE_META[s as ViolationSource] ?? SOURCE_META.transcript;

interface Props {
  text: string;
  percent: number;
  className?: string;
}

/** 长任务的加载态：转圈 + 状态文字 + 进度条。 */
export function ProgressBlock({ text, percent, className = "p-6" }: Props) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 ${className}`}>
      <span className="loading loading-spinner loading-lg text-primary" />
      <span className="text-base-content/60 text-sm">{text}</span>
      <div className="w-full max-w-xs">
        <progress className="progress progress-primary w-full" value={percent} max={100} />
        <span className="text-xs text-base-content/40 mt-1 block text-center">
          {Math.round(percent)}%
        </span>
      </div>
    </div>
  );
}

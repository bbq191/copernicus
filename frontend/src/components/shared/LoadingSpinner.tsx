export function LoadingSpinner({ text = "加载中..." }: { text?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 p-8">
      <span className="loading loading-spinner loading-lg text-primary" />
      <span className="text-base-content/60">{text}</span>
    </div>
  );
}

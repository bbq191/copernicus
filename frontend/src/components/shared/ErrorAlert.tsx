import { CircleAlert } from "lucide-react";

interface Props {
  message: string;
  onRetry?: () => void;
  compact?: boolean;
}

export function ErrorAlert({ message, onRetry, compact }: Props) {
  return (
    <div
      role="alert"
      className={`alert alert-error ${compact ? "py-2 px-3 text-sm" : ""}`}
    >
      <CircleAlert className={compact ? "h-4 w-4" : "h-5 w-5"} />
      <span>{message}</span>
      {onRetry && (
        <button
          className={`btn btn-ghost ${compact ? "btn-xs" : "btn-sm"}`}
          onClick={onRetry}
        >
          重试
        </button>
      )}
    </div>
  );
}

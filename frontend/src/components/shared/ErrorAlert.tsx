import { CircleAlert } from "lucide-react";

interface Props {
  message: string;
  onRetry?: () => void;
}

export function ErrorAlert({ message, onRetry }: Props) {
  return (
    <div role="alert" className="alert alert-error">
      <CircleAlert className="h-5 w-5" />
      <span>{message}</span>
      {onRetry && (
        <button className="btn btn-sm btn-ghost" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}

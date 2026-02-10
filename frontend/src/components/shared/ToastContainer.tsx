import { X } from "lucide-react";
import { useToastStore } from "../../stores/toastStore";
import type { ToastType } from "../../stores/toastStore";

const ALERT_CLASS: Record<ToastType, string> = {
  success: "alert-success",
  error: "alert-error",
  info: "alert-info",
  warning: "alert-warning",
};

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  const removeToast = useToastStore((s) => s.removeToast);

  if (toasts.length === 0) return null;

  return (
    <div className="toast toast-end toast-bottom z-50">
      {toasts.map((t) => (
        <div key={t.id} className={`alert ${ALERT_CLASS[t.type]} shadow-lg`}>
          <span>{t.message}</span>
          <button
            className="btn btn-ghost btn-xs"
            onClick={() => removeToast(t.id)}
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      ))}
    </div>
  );
}

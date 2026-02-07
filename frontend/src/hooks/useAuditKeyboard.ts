import { useEffect } from "react";
import { usePlayerStore } from "../stores/playerStore";
import { useComplianceStore } from "../stores/complianceStore";

const LOOP_PADDING_MS = 10000;

function jumpToSelected() {
  const v = useComplianceStore.getState().selectedViolation;
  if (!v) return;
  const player = usePlayerStore.getState();
  const startMs = Math.max(0, v.timestamp_ms - 5000);
  const endMs = (v.end_ms || v.timestamp_ms) + LOOP_PADDING_MS;
  player.setLoopRegion({ startMs, endMs });
  player.seekAndPlay(startMs);
}

export function useAuditKeyboard(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        return;
      }

      const store = useComplianceStore.getState();

      switch (e.key) {
        case " ": {
          e.preventDefault();
          usePlayerStore.getState().togglePlay();
          break;
        }
        case "Enter": {
          e.preventDefault();
          if (store.selectedViolation && store.selectedViolation.status === "pending") {
            store.setViolationStatus(store.selectedViolation, "confirmed");
          }
          break;
        }
        case "Delete":
        case "Backspace": {
          e.preventDefault();
          if (store.selectedViolation && store.selectedViolation.status === "pending") {
            store.setViolationStatus(store.selectedViolation, "rejected");
          }
          break;
        }
        case "ArrowDown": {
          e.preventDefault();
          store.navigateViolation("next");
          jumpToSelected();
          break;
        }
        case "ArrowUp": {
          e.preventDefault();
          store.navigateViolation("prev");
          jumpToSelected();
          break;
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [enabled]);
}

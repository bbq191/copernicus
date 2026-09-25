import { useEffect } from "react";
import { usePlayerStore } from "../stores/playerStore";
import { selectSelectedViolation, useComplianceStore } from "../stores/complianceStore";
import { playViolation } from "../utils/violationPlayback";

function jumpToSelected() {
  const v = selectSelectedViolation(useComplianceStore.getState());
  if (v) playViolation(v);
}

/** 只处理待审项：已复核的违规不响应快捷键，避免误按覆盖结论 */
function reviewSelected(status: "confirmed" | "rejected") {
  const store = useComplianceStore.getState();
  const v = selectSelectedViolation(store);
  if (v && v.status === "pending") store.setViolationStatus(v, status);
}

/** 输入类控件自己处理键盘，全局快捷键不能抢 */
function isTyping(el: HTMLElement): boolean {
  return el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable;
}

/** 可点击控件：Enter/Space 是它们的激活键，不能被"确认/播放"劫持 */
function isActivatable(el: HTMLElement): boolean {
  return el.closest("button, a, select, summary, [role='button']") !== null;
}

export function useAuditKeyboard(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (isTyping(target)) return;

      const store = useComplianceStore.getState();

      // Ctrl/Cmd+A: select all (batch mode only)
      if ((e.ctrlKey || e.metaKey) && e.key === "a") {
        if (store.batchMode) {
          e.preventDefault();
          store.selectAll();
        }
        return;
      }

      // 带修饰键的组合留给浏览器/系统（如 Ctrl+B、Cmd+Enter）
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if ((e.key === " " || e.key === "Enter") && isActivatable(target)) return;

      switch (e.key) {
        case " ": {
          e.preventDefault();
          usePlayerStore.getState().togglePlay();
          break;
        }
        case "Enter": {
          e.preventDefault();
          reviewSelected("confirmed");
          break;
        }
        case "Delete":
        case "Backspace": {
          e.preventDefault();
          reviewSelected("rejected");
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
        case "b":
        case "B": {
          e.preventDefault();
          store.toggleBatchMode();
          break;
        }
        case "Escape": {
          e.preventDefault();
          if (store.evidenceDetailId) {
            store.closeEvidenceDetail();
          } else if (store.batchMode) {
            store.toggleBatchMode();
          }
          break;
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [enabled]);
}

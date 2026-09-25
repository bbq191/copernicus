import { Moon, Sun } from "lucide-react";
import { useCallback, useState } from "react";
import { writeStorage } from "../../utils/safeStorage";

// index.html 里的内联脚本已在首帧前按 localStorage 设置了 data-theme，这里直接读 DOM 保持一致
function isDarkNow(): boolean {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

export function ThemeToggle() {
  const [dark, setDark] = useState(isDarkNow);

  const toggle = useCallback(() => {
    const next = !dark;
    setDark(next);
    const theme = next ? "dark" : "corporate";
    document.documentElement.setAttribute("data-theme", theme);
    writeStorage("theme", theme);
  }, [dark]);

  return (
    <label className="swap swap-rotate btn btn-ghost btn-circle">
      <input type="checkbox" checked={dark} onChange={toggle} />
      <Sun className="swap-off h-5 w-5" />
      <Moon className="swap-on h-5 w-5" />
    </label>
  );
}

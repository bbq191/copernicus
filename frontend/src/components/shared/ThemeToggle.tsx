import { Moon, Sun } from "lucide-react";
import { useCallback, useState } from "react";

function getInitialTheme(): boolean {
  return localStorage.getItem("theme") === "dark";
}

export function ThemeToggle() {
  const [dark, setDark] = useState(getInitialTheme);

  const toggle = useCallback(() => {
    const next = !dark;
    setDark(next);
    const theme = next ? "dark" : "corporate";
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [dark]);

  return (
    <label className="swap swap-rotate btn btn-ghost btn-circle">
      <input type="checkbox" checked={dark} onChange={toggle} />
      <Sun className="swap-off h-5 w-5" />
      <Moon className="swap-on h-5 w-5" />
    </label>
  );
}

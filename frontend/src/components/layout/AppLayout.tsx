import { ThemeToggle } from "../shared/ThemeToggle";
import { LeftPanel } from "./LeftPanel";
import { RightPanel } from "./RightPanel";
import { useNavigate } from "react-router-dom";

export function AppLayout() {
  const navigate = useNavigate();

  return (
    <div className="flex flex-col h-screen">
      <div className="navbar bg-base-100 border-b border-base-300 px-4">
        <div className="flex-1">
          <button
            className="btn btn-ghost text-xl"
            onClick={() => navigate("/")}
          >
            Copernicus
          </button>
        </div>
        <div className="flex-none">
          <ThemeToggle />
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="w-[400px] shrink-0">
          <LeftPanel />
        </div>
        <div className="flex-1">
          <RightPanel />
        </div>
      </div>
    </div>
  );
}

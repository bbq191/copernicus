import { useState } from "react";
import { ThemeToggle } from "../shared/ThemeToggle";
import { LeftPanel } from "./LeftPanel";
import { RightPanel } from "./RightPanel";
import { EvidenceDetailPanel } from "../compliance/EvidenceDetailPanel";
import { useComplianceStore } from "../../stores/complianceStore";
import { useNavigate, Link } from "react-router-dom";
import { Activity, FileText, LayoutDashboard, ListChecks } from "lucide-react";

/** 移动端（&lt;lg）一次只显示一个面板；桌面端两栏始终同时显示，不受这个状态影响。 */
type MobilePane = "workspace" | "content";

export function AppLayout() {
  const navigate = useNavigate();
  const evidencePanelOpen = useComplianceStore((s) => s.evidenceDetailId !== null);
  const [mobilePane, setMobilePane] = useState<MobilePane>("workspace");

  return (
    <div className="flex flex-col h-screen">
      {/* Navbar */}
      <div className="navbar bg-base-100 border-b border-base-300 px-4 min-h-12">
        <div className="flex-1">
          <button
            className="btn btn-ghost text-xl"
            onClick={() => navigate("/")}
          >
            Copernicus
          </button>
        </div>
        <div className="flex-none flex items-center gap-1">
          <Link
            to="/rules"
            className="btn btn-ghost btn-sm btn-square"
            title="规则库"
          >
            <ListChecks className="h-4 w-4" />
          </Link>
          <Link
            to="/health"
            className="btn btn-ghost btn-sm btn-square"
            title="服务状态"
          >
            <Activity className="h-4 w-4" />
          </Link>
          <ThemeToggle />
        </div>
      </div>

      {/* 工作区主体：桌面端三栏并排；移动端用底部 Tab 在前两栏间切换，证据详情始终是全屏弹层 */}
      <div className="flex flex-1 overflow-hidden pb-16 lg:pb-0">
        {/* 左栏：播放器 + 摘要 + 合规配置 + 音频重塑 */}
        <div
          className={`${mobilePane === "workspace" ? "block" : "hidden"} lg:block w-full lg:w-[26.25rem] lg:shrink-0 overflow-y-auto`}
        >
          <LeftPanel />
        </div>

        {/* 中栏：转写结果 / 违规报告（内部自带 tab） */}
        <div
          className={`${mobilePane === "content" ? "block" : "hidden"} lg:block flex-1 min-w-0`}
        >
          <RightPanel />
        </div>

        {/* 证据详情：任意宽度下都是"钻取详情"，移动端全屏弹层，桌面端第三栏 */}
        {evidencePanelOpen && (
          <div className="fixed inset-0 z-50 bg-base-100 lg:static lg:inset-auto lg:z-auto lg:w-[23.75rem] lg:shrink-0 lg:border-l lg:border-base-300 overflow-y-auto">
            <EvidenceDetailPanel />
          </div>
        )}
      </div>

      {/* 移动端底部 Tab：切换左栏/中栏，桌面端两栏同时显示，不需要这个导航 */}
      <div className="dock lg:hidden">
        <button
          className={mobilePane === "workspace" ? "dock-active" : ""}
          onClick={() => setMobilePane("workspace")}
        >
          <LayoutDashboard className="h-5 w-5" />
          <span className="dock-label">工作区</span>
        </button>
        <button
          className={mobilePane === "content" ? "dock-active" : ""}
          onClick={() => setMobilePane("content")}
        >
          <FileText className="h-5 w-5" />
          <span className="dock-label">转写/审核</span>
        </button>
      </div>
    </div>
  );
}

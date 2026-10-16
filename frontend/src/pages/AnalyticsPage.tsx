import { useNavigate } from "react-router-dom";
import { RefreshCw, BarChart3 } from "lucide-react";
import { useComplianceTrends } from "../hooks/useComplianceTrends";
import { ThemeToggle } from "../components/shared/ThemeToggle";
import { SEVERITY_META } from "../components/compliance/violationMeta";

const SEVERITY_ORDER = ["high", "medium", "low"] as const;
const SEVERITY_PROGRESS_CLASS: Record<(typeof SEVERITY_ORDER)[number], string> = {
  high: "progress-error",
  medium: "progress-warning",
  low: "progress-info",
};

export function AnalyticsPage() {
  const navigate = useNavigate();
  const { data, loading, error, refresh } = useComplianceTrends();

  const maxRuleCount = data ? Math.max(1, ...data.top_rules.map((r) => r.count)) : 1;
  const maxSeverityCount = data
    ? Math.max(1, ...SEVERITY_ORDER.map((s) => data.severity_counts[s] ?? 0))
    : 1;

  return (
    <div className="min-h-screen flex flex-col">
      <div className="navbar bg-base-100 border-b border-base-300 px-4 min-h-12">
        <div className="flex-1">
          <button className="btn btn-ghost text-xl" onClick={() => navigate("/")}>
            Copernicus
          </button>
          <span className="text-base-content/40 ml-1">/ 合规趋势</span>
        </div>
        <div className="flex-none flex items-center gap-1">
          <button
            className="btn btn-ghost btn-sm btn-square"
            onClick={refresh}
            disabled={loading}
            title="刷新"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
          <ThemeToggle />
        </div>
      </div>

      <div className="flex-1 p-4 sm:p-6 max-w-2xl mx-auto w-full">
        <div className="flex items-center gap-2 mb-6">
          <BarChart3 className="h-5 w-5" />
          <h1 className="text-xl font-semibold">合规审核趋势</h1>
        </div>

        {error && (
          <div className="alert alert-error mb-4">
            <span className="text-sm">{error}</span>
          </div>
        )}

        {!data && !error && (
          <div className="flex justify-center py-16">
            <span className="loading loading-spinner loading-lg text-primary" />
          </div>
        )}

        {data && (
          <div className="flex flex-col gap-4">
            {data.total_tasks === 0 ? (
              <p className="text-sm text-base-content/40 text-center py-16">
                还没有已完成的合规审核任务
              </p>
            ) : (
              <>
                {/* 总览 */}
                <div className="card bg-base-100 border border-base-300 shadow-sm">
                  <div className="card-body py-4 px-5 flex-row justify-between">
                    <div>
                      <div className="text-2xl font-bold">{data.total_tasks}</div>
                      <div className="text-xs text-base-content/50 mt-1">已审核任务</div>
                    </div>
                    <div className="text-right">
                      <div className="text-2xl font-bold">
                        {data.avg_compliance_score ?? "-"}
                      </div>
                      <div className="text-xs text-base-content/50 mt-1">平均合规分</div>
                    </div>
                  </div>
                </div>

                {/* 严重度分布 */}
                <div className="card bg-base-100 border border-base-300 shadow-sm">
                  <div className="card-body py-4 px-5">
                    <h2 className="card-title text-sm text-base-content/60 mb-3">
                      违规严重度分布
                    </h2>
                    <div className="flex flex-col gap-2">
                      {SEVERITY_ORDER.map((sev) => {
                        const count = data.severity_counts[sev] ?? 0;
                        return (
                          <div key={sev} className="flex items-center gap-3">
                            <span className={`text-xs w-8 shrink-0 ${SEVERITY_META[sev].text}`}>
                              {SEVERITY_META[sev].label}
                            </span>
                            <progress
                              className={`progress flex-1 ${SEVERITY_PROGRESS_CLASS[sev]}`}
                              value={count}
                              max={maxSeverityCount}
                            />
                            <span className="text-xs w-6 text-right shrink-0">{count}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>

                {/* 高频违规规则排行 */}
                <div className="card bg-base-100 border border-base-300 shadow-sm">
                  <div className="card-body py-4 px-5">
                    <h2 className="card-title text-sm text-base-content/60 mb-3">
                      高频违规规则（已排除驳回的误报）
                    </h2>
                    {data.top_rules.length === 0 ? (
                      <p className="text-xs text-base-content/40">暂无命中记录</p>
                    ) : (
                      <div className="flex flex-col gap-3">
                        {data.top_rules.map((rule) => (
                          <div key={rule.rule_id} className="flex flex-col gap-1">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-sm truncate">
                                规则 {rule.rule_id} · {rule.rule_content}
                              </span>
                              <span className="text-xs text-base-content/50 shrink-0">
                                {rule.count} 次
                              </span>
                            </div>
                            <progress
                              className="progress progress-primary w-full"
                              value={rule.count}
                              max={maxRuleCount}
                            />
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

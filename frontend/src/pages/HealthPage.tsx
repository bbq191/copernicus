import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { RefreshCw, Activity } from "lucide-react";
import { getHealth } from "../api/health";
import type { HealthResponse, ComponentStatus } from "../api/health";
import { ThemeToggle } from "../components/shared/ThemeToggle";

const REFRESH_INTERVAL_MS = 10_000;

const STATUS_BADGE: Record<string, string> = {
  healthy: "badge-success",
  degraded: "badge-warning",
  unhealthy: "badge-error",
  ok: "badge-success",
  down: "badge-error",
};

const STATUS_LABEL: Record<string, string> = {
  healthy: "正常",
  degraded: "降级",
  unhealthy: "不可用",
  ok: "正常",
  down: "离线",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge badge-sm font-medium ${STATUS_BADGE[status] ?? "badge-neutral"}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

function ComponentRow({
  label,
  component,
}: {
  label: string;
  component: ComponentStatus;
}) {
  return (
    <div className="flex items-start justify-between py-3 border-b border-base-200 last:border-0">
      <div className="flex flex-col gap-1">
        <span className="font-medium text-sm">{label}</span>
        {component.detail && (
          <span className="text-xs text-base-content/50">{component.detail}</span>
        )}
      </div>
      <StatusBadge status={component.status} />
    </div>
  );
}

export function HealthPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getHealth();
      setData(result);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const timer = setInterval(fetchHealth, REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchHealth]);

  const overallColor =
    data?.status === "healthy"
      ? "text-success"
      : data?.status === "degraded"
        ? "text-warning"
        : "text-error";

  return (
    <div className="min-h-screen flex flex-col">
      <div className="navbar bg-base-100 border-b border-base-300 px-4 min-h-12">
        <div className="flex-1">
          <button className="btn btn-ghost text-xl" onClick={() => navigate("/")}>
            Copernicus
          </button>
          <span className="text-base-content/40 ml-1">/ 服务状态</span>
        </div>
        <div className="flex-none gap-2">
          <ThemeToggle />
        </div>
      </div>

      <div className="flex-1 p-6 max-w-2xl mx-auto w-full">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            <h1 className="text-xl font-semibold">服务健康状态</h1>
          </div>
          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span className="text-xs text-base-content/40">
                更新于 {lastUpdated.toLocaleTimeString()}
              </span>
            )}
            <button
              className="btn btn-ghost btn-sm btn-square"
              onClick={fetchHealth}
              disabled={loading}
              title="立即刷新"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {error && (
          <div className="alert alert-error mb-4">
            <span className="text-sm">{error}</span>
          </div>
        )}

        {data && (
          <div className="flex flex-col gap-4">
            {/* 整体状态 */}
            <div className="card bg-base-100 border border-base-300 shadow-sm">
              <div className="card-body py-4 px-5">
                <div className="flex items-center justify-between">
                  <span className="font-semibold">整体状态</span>
                  <span className={`text-2xl font-bold ${overallColor}`}>
                    {STATUS_LABEL[data.status] ?? data.status}
                  </span>
                </div>
              </div>
            </div>

            {/* 组件状态 */}
            <div className="card bg-base-100 border border-base-300 shadow-sm">
              <div className="card-body py-4 px-5">
                <h2 className="card-title text-sm text-base-content/60 mb-1">组件</h2>
                <ComponentRow label="ASR 语音识别" component={data.asr} />
                <ComponentRow label="LLM 语言模型" component={data.llm} />
                {data.tts && <ComponentRow label="TTS 语音合成" component={data.tts} />}
              </div>
            </div>

            {/* 任务队列 */}
            <div className="card bg-base-100 border border-base-300 shadow-sm">
              <div className="card-body py-4 px-5">
                <h2 className="card-title text-sm text-base-content/60 mb-3">任务队列</h2>
                <div className="grid grid-cols-4 gap-4 text-center">
                  <div>
                    <div className="text-2xl font-bold text-primary">{data.tasks.active}</div>
                    <div className="text-xs text-base-content/50 mt-1">运行中</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold">{data.tasks.completed}</div>
                    <div className="text-xs text-base-content/50 mt-1">已完成</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-error">{data.tasks.failed}</div>
                    <div className="text-xs text-base-content/50 mt-1">失败</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-secondary">{data.tasks.synthesis_running}</div>
                    <div className="text-xs text-base-content/50 mt-1">合成中</div>
                  </div>
                </div>
              </div>
            </div>

            {/* VRAM */}
            {data.vram && (
              <div className="card bg-base-100 border border-base-300 shadow-sm">
                <div className="card-body py-4 px-5">
                  <h2 className="card-title text-sm text-base-content/60 mb-3">显存（VRAM）</h2>
                  <div className="flex flex-col gap-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-base-content/60">已用 / 预算</span>
                      <span className="font-medium">
                        {data.vram.estimated_used_gb.toFixed(1)} GB
                        {" / "}
                        {data.vram.budget_gb.toFixed(1)} GB
                      </span>
                    </div>
                    <progress
                      className="progress progress-primary w-full"
                      value={data.vram.estimated_used_gb}
                      max={data.vram.budget_gb}
                    />
                    {data.vram.loaded_models.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {data.vram.loaded_models.map((m) => (
                          <span key={m} className="badge badge-outline badge-sm">{m}</span>
                        ))}
                      </div>
                    )}
                    {data.vram.loaded_models.length === 0 && (
                      <span className="text-xs text-base-content/40">暂无模型加载</span>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {!data && !error && (
          <div className="flex justify-center py-16">
            <span className="loading loading-spinner loading-lg text-primary" />
          </div>
        )}
      </div>
    </div>
  );
}

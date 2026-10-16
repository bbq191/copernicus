import { useEffect, useState } from "react";
import { getComplianceTrends } from "../api/compliance";
import { errorMessage } from "../api/errors";
import type { ComplianceTrends } from "../types/compliance";

/** 合规趋势仪表盘的数据加载：一次性全量聚合，不是实时指标，靠手动刷新获取最新结果。 */
export function useComplianceTrends() {
  const [data, setData] = useState<ComplianceTrends | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let ignore = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await getComplianceTrends();
        if (!ignore) setData(result);
      } catch (err) {
        if (!ignore) setError(errorMessage(err, "加载合规趋势失败"));
      } finally {
        if (!ignore) setLoading(false);
      }
    })();
    return () => {
      ignore = true;
    };
  }, [version]);

  const refresh = () => setVersion((v) => v + 1);

  return { data, loading, error, refresh };
}

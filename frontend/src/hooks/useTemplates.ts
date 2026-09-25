import { useEffect, useState } from "react";
import { listTemplates } from "../api/templates";
import type { TemplateInfo } from "../api/templates";

// 模板列表在一次会话内基本不变：只请求一次，多个面板共享结果
let cached: Promise<TemplateInfo[]> | null = null;

function loadTemplates(): Promise<TemplateInfo[]> {
  cached ??= listTemplates().catch(() => {
    cached = null; // 失败不缓存，下次挂载重试
    return [];
  });
  return cached;
}

export function useTemplates(): TemplateInfo[] {
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  useEffect(() => {
    let alive = true;
    void loadTemplates().then((list) => alive && setTemplates(list));
    return () => {
      alive = false;
    };
  }, []);
  return templates;
}

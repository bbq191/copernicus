# Copernicus 前端技术学习手册

> **阅读前提**：本文档结合 Copernicus 前端源码（`frontend/src/`）讲解现代 React 工程的核心知识点。每课对应真实文件，讲解的所有技术决策都能在源码中找到依据。

---

## 第一课：TypeScript 类型系统

### 1.1 为什么先学类型？

TypeScript 类型是前端架构的"合同"。API 响应数据一旦有明确的类型约束，组件代码就不会猜测字段是否存在，编译器会提前拦截错误。

### 1.2 联合类型与字面量类型

`types/task.ts` 中定义任务状态：

```
TaskStatus = "pending" | "processing_asr" | "extracting_frames" | ...
```

与后端 `TaskStatus(StrEnum)` 一一对应。联合类型的好处是：`switch (status)` 时 TypeScript 能检查是否穷举了所有分支，遗漏会报错。

### 1.3 接口嵌套与可选字段

```
interface TaskResultsResponse {
  transcript: TranscriptResponse | null;   // 可能尚未完成
  evaluation: EvaluationResult | null;
  has_synthesis: boolean;                  // 服务端文件探测结果
  ...
}
```

`| null` 强制调用方在使用前做判断，杜绝运行时 `Cannot read properties of null`。

### 1.4 类型导入与再导出

各模块只暴露本层需要的类型，其他模块通过 `import type { Xxx }` 引入——`import type` 只在编译期存在，不影响运行时 bundle 大小。

**关键文件**：`types/task.ts`、`types/evaluation.ts`、`types/compliance.ts`、`types/transcript.ts`、`types/view.ts`

---

## 第二课：React 组件与 JSX

### 2.1 函数组件与 Props 类型

Copernicus 所有组件都是函数组件，使用 `interface` 声明 Props：

```
interface ErrorAlertProps {
  message: string;
  compact?: boolean;
  onRetry?: () => void;
}
```

`?` 表示可选，调用方可以不传，组件内用默认值兜底。

### 2.2 条件渲染

```
{hasSynthesis && taskId && (
  <audio ref={audioRef} src={getSynthesisAudioUrl(taskId)} ... />
)}
```

短路运算符 `&&` 是最常见的条件渲染写法。注意 `0 && <Comp />` 会渲染数字 `0`——改用 `count > 0 && <Comp />` 规避。

### 2.3 列表渲染与 key

`TranscriptList.tsx` 将 `filteredBlocks` 交给 Virtuoso 渲染，Virtuoso 内部要求每项有稳定 key（`block.id`），避免重渲染时 DOM 乱序。

### 2.4 Fragment 与布局

`AppLayout` 用 `<div className="flex ...">` 构建整体格局，不需要多余的 DOM 层级时可用 `<>...</>` Fragment 包裹多个元素。

**关键文件**：`components/shared/ErrorAlert.tsx`、`components/layout/AppLayout.tsx`

---

## 第三课：React Hooks 基础

### 3.1 useState — 局部 UI 状态

`SynthesisPanel.tsx` 使用三个独立 `useState`：

```
const [loading, setLoading] = useState(false);   // 按钮 loading 态
const [playing, setPlaying] = useState(false);    // 播放/暂停
const [currentTime, setCurrentTime] = useState(0); // 进度条当前值
```

这三个状态生命周期相同（随组件销毁），且只需在这一个组件内感知，所以用 `useState` 而不是全局 store。

### 3.2 useEffect — 副作用与清理

`WorkspacePage.tsx` 在 mount 时恢复持久化结果：

```
useEffect(() => {
  let cancelled = false;
  getTaskResults(taskId).then((res) => {
    if (cancelled) return;
    // 写入各 store ...
  });
  return () => { cancelled = true; };   // 清理：组件卸载时标记取消
}, [taskId]);
```

`cancelled` 标志防止组件卸载后异步回调仍然修改 state（内存泄漏 + 无效更新）。

### 3.3 useRef — 跨渲染保存引用

`SynthesisPanel.tsx` 用 `useRef<HTMLAudioElement>(null)` 持有 `<audio>` DOM 元素的引用，可以直接调用 `audio.play()` / `audio.load()` 而不触发组件重渲染。

`useTaskPolling.ts` 用 `useRef<ReturnType<typeof setInterval>>` 保存定时器 ID，在 effect 清理时 `clearInterval`，避免内存泄漏。

### 3.4 useCallback — 稳定函数引用

`SummaryPanel.tsx` 中 `handleRerun` 包在 `useCallback` 里，依赖数组 `[taskId, rawEntries, templateId]` 确保只有这些值变化时才重建函数，防止触发子组件不必要的重渲染。

**关键文件**：`components/synthesis/SynthesisPanel.tsx`、`pages/WorkspacePage.tsx`

---

## 第四课：自定义 Hook

自定义 Hook 是将 React Hooks 逻辑复用的核心手段——函数名以 `use` 开头，内部可以调用其他 Hook。

### 4.1 useTaskPolling — 轮询状态机

```
export function useTaskPolling(enabled = true) {
  const taskId = useTaskStore((s) => s.taskId);
  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    if (!enabled || !taskId || status === "completed") return;
    const poll = async () => { ... };
    poll();
    timerRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(timerRef.current);
  }, [enabled, taskId, status, ...]);
}
```

设计要点：
- `enabled` 参数允许调用方在恢复持久化结果前暂停轮询，避免竞态
- effect 返回清理函数 `clearInterval`，路由切换时定时器自动停止
- 任务完成后在 `if (res.status === "completed")` 分支内手动 `clearInterval`

### 4.2 useAudioSync — RAF 时间同步

```
export function useAudioSync(mediaRef) {
  const tick = () => {
    const nowMs = el.currentTime * 1000;
    if (Math.abs(nowMs - lastTimeRef.current) >= 50) {
      lastTimeRef.current = nowMs;
      setCurrentTime(nowMs);             // 写入全局 playerStore
    }
    rafRef.current = requestAnimationFrame(tick);
  };
  rafRef.current = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(rafRef.current);
}
```

使用 `requestAnimationFrame`（RAF）而非 `setInterval` 的原因：RAF 与浏览器渲染帧同步（约 16ms），精度更高，且页面隐藏时自动暂停，节省 CPU。

### 4.3 useAutoScroll — 智能滚动

`useAutoScroll` 订阅 `playerStore.currentTime`，调用 `findBlockIndex` 二分查找当前播放段落，再通过 `VirtuosoHandle.scrollToIndex` 滚动到对应位置。

mount 后的首次滚动用 `requestAnimationFrame + setTimeout(150ms)` 双重保险，等待 Virtuoso 内部初始化完成。

**关键文件**：`hooks/useTaskPolling.ts`、`hooks/useAudioSync.ts`、`hooks/useAutoScroll.ts`

---

## 第五课：Zustand 全局状态管理

### 5.1 为什么不用 Redux？

Redux 需要 Provider、Action、Reducer 三层模板代码。Zustand 只需一个 `create` 调用，直接在任意组件或普通函数中 `useXxxStore()` 即可读写，**无需 Provider 包裹**。

### 5.2 store 的基本结构

```
export const useTaskStore = create<TaskState>((set) => ({
  taskId: null,
  status: null,
  setTask: (taskId, status) => set({ taskId, status, ... }),
  updateStatus: (status, progress) =>
    set((state) => ({ status, progress, isVideoTask: ... })),
}));
```

`set` 接受对象（浅合并）或函数（需要读取旧状态时用函数形式）。

### 5.3 选择器（Selector）

```
const taskId = useTaskStore((s) => s.taskId);
```

组件只订阅它需要的字段。`taskId` 变化时组件重渲染；`status` 变化时不重渲染——精细控制渲染范围。

### 5.4 在非组件代码中访问 store

`useTaskPolling.ts` 中在 effect 内用 `useXxxStore.getState()` 直接读写 store，绕过 Hook 规则限制（Hook 只能在组件或自定义 Hook 顶层调用）：

```
useEvaluationStore.getState().setEvaluation(results.evaluation);
useSynthesisStore.getState().setHasSynthesis(true);
```

### 5.5 七个 store 的职责划分

| Store | 职责 |
|---|---|
| taskStore | 任务 ID、状态、进度、轮询开关 |
| transcriptStore | 原始条目、合并块、说话人映射、搜索过滤 |
| evaluationStore | 摘要结果、加载态、进度百分比 |
| complianceStore | 合规报告、规则列表 |
| playerStore | 媒体时间、播放态、循环区间、媒体元素引用 |
| synthesisStore | 是否已合成、音频时长、合成耗时 |
| toastStore | 全局通知队列 |

**关键文件**：`stores/` 目录下全部文件

---

## 第六课：跨组件协调

### 6.1 受控折叠面板

`LeftPanel.tsx` 中，智能摘要和合规审核用 DaisyUI 的 `defaultChecked`（非受控）初始展开，而音频重塑面板用受控模式：

```
const [synthesisOpen, setSynthesisOpen] = useState(false);

useEffect(() => {
  if (hasSynthesis) setSynthesisOpen(true);
}, [hasSynthesis]);

<input
  type="checkbox"
  checked={synthesisOpen}                        // 受控
  onChange={(e) => setSynthesisOpen(e.target.checked)}
/>
```

**原因**：`defaultChecked` 是初始值，组件 mount 后异步检测到 `has_synthesis` 为 true 时，无法再改变折叠状态。改用受控模式，`hasSynthesis` 变化时 `useEffect` 触发 `setSynthesisOpen(true)` 自动展开面板。

### 6.2 store 间协调不用事件总线

Copernicus 没有事件总线（EventEmitter），多 store 协调靠的是在同一个地方（`WorkspacePage.tsx`、`useTaskPolling.ts`）集中读取结果，然后分别写入各 store：

```
// useTaskPolling.ts — 完成时集中分发
if (results.has_synthesis) useSynthesisStore.getState().setHasSynthesis(true);
if (results.evaluation)    useEvaluationStore.getState().setEvaluation(...);
setRawEntries(transcript.transcript);  // 最后写 transcript，触发 SummaryPanel
```

`setRawEntries` 放在最后，是因为 SummaryPanel 的 `useEffect` 监听 `rawEntries`——只有 evaluation 已经写入 store，SummaryPanel 才会看到 `existing` 为 true，跳过自动重新评估。

### 6.3 useMemo 过滤列表

`TranscriptList.tsx` 中：

```
const filteredBlocks = useMemo(
  () => blocks.filter((b) => visibleSpeakers.has(b.speaker)),
  [blocks, visibleSpeakers],
);
```

`useMemo` 缓存计算结果，只有 `blocks` 或 `visibleSpeakers` 变化时重新过滤，避免每次渲染都遍历全部 block。

**关键文件**：`components/layout/LeftPanel.tsx`、`hooks/useTaskPolling.ts`

---

## 第七课：异步通信与 API 设计

### 7.1 Axios 客户端封装

`api/client.ts` 统一配置：

- `baseURL: "/api/v1"` — 所有请求自动加前缀
- `timeout: 600_000` — 长达 10 分钟，兼容大文件上传和 LLM 推理
- `maxBodyLength: Infinity` — 禁用 axios 自带的请求体大小限制

响应拦截器将 `error.response?.data?.detail` 提取为 `Error.message`，并把 HTTP 状态码附到 `statusCode` 字段，供调用方判断是否可重试。

### 7.2 小文件上传与重试

```
async function uploadWithRetry(form: FormData): Promise<TaskSubmitResponse> {
  for (let attempt = 0; attempt < UPLOAD_MAX_RETRIES; attempt++) {
    if (attempt > 0) await new Promise((r) => setTimeout(r, 2 ** attempt * 1000));
    try { return await client.post(...); }
    catch (err) { if (!isRetryable(err)) throw err; }
  }
}
```

`isRetryable` 判断 `statusCode >= 500` 才重试，4xx（如 400 参数错误）不重试——避免无效重试浪费时间。退避时间 `2^attempt` 秒：第 1 次 2s，第 2 次 4s。

### 7.3 分片上传（断点续传）

超过 20MB 的文件走分片路径：

```
步骤 1：GET /uploads/{hash}?filename=...&total_size=...
         → 返回 {offset, complete, task_id}
         → offset=0：新上传；offset>0：断点续传；complete=true：已存在

步骤 2：while (offset < file.size)
         PATCH /uploads/{hash}
         Content-Range: bytes {offset}-{end}/{total}
         Body: 5MB ArrayBuffer
         → 返回 {received, complete, task_id}
```

失败重试前先 `GET` 查询服务端已收到的 offset，避免重复发送已接收的块。

### 7.4 长轮询评估结果

`api/evaluation.ts` 发起评估后进入自定义轮询循环：

```
while (true) {
  const { data } = await client.get(`/tasks/${taskId}`);
  if (data.status === "completed") return data.result.evaluation;
  if (data.status === "failed") throw new Error(data.error);
  store().setProgress(data.progress.percent, STATUS_TEXT[data.status]);
  await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
}
```

每轮更新进度条（`setProgress`），用户能看到百分比滚动，减少等待焦虑。

**关键文件**：`api/client.ts`、`api/task.ts`、`utils/chunkedUpload.ts`、`api/evaluation.ts`

---

## 第八课：性能优化

### 8.1 虚拟滚动（Virtuoso）

转录稿可能有数千条 `MergedBlock`。`TranscriptList.tsx` 使用 `react-virtuoso` 虚拟滚动，DOM 中只保留视口内可见的块，极大降低内存占用和渲染耗时。

Virtuoso 的 `overscan={200}` 让上下额外预渲染 200px，滚动时无空白闪烁。

### 8.2 二分查找

`utils/findBlockIndex.ts` 实现经典二分查找，在已按时间排序的 `blocks` 数组中 O(log n) 找到当前播放时间对应的块：

```
const mid = (lo + hi) >>> 1;   // 无符号右移 1 位 = Math.floor((lo+hi)/2)，且不会溢出
```

`>>>` 运算符将结果转为无符号 32 位整数再右移，即使 `lo + hi` 超过 `2^31` 也不产生负数。

### 8.3 RAF 节流（useAudioSync）

`useAudioSync` 用 `requestAnimationFrame` 驱动时间同步，每帧（16ms）最多一次更新，且加了 50ms 阈值过滤：

```
if (Math.abs(nowMs - lastTimeRef.current) >= 50) {
  lastTimeRef.current = nowMs;
  setCurrentTime(nowMs);
}
```

`setCurrentTime` 会触发 `useAutoScroll` 重新计算滚动位置，50ms 阈值防止每帧都触发二分查找 + 滚动。

### 8.4 SHA-256 Web Crypto API

`utils/fileHash.ts` 用浏览器原生 `crypto.subtle.digest("SHA-256", buffer)` 计算文件哈希，无需引入第三方库，且 `crypto.subtle` 在 HTTPS 或 localhost 下可用。

**关键文件**：`components/transcript/TranscriptList.tsx`、`utils/findBlockIndex.ts`、`hooks/useAudioSync.ts`、`utils/fileHash.ts`

---

## 第九课：项目里 10 个最有趣的技巧

### 技巧 1：await 顺序决定正确性

`useTaskPolling.ts` 的任务完成分支：

```
// ✅ 正确顺序
const results = await getTaskResults(taskId);  // 先写 evaluation store
setRawEntries(transcript.transcript);           // 再触发 SummaryPanel

// ❌ 错误顺序（会导致 SummaryPanel 看到 existing=null，用默认模板重复评估）
setRawEntries(transcript.transcript);
const results = await getTaskResults(taskId);
```

两行代码调换会引发 race condition，页面行为完全不同。

---

### 技巧 2：Web Crypto SHA-256（无依赖）

```
const buffer = await file.arrayBuffer();
const hashBuffer = await crypto.subtle.digest("SHA-256", buffer);
return Array.from(new Uint8Array(hashBuffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
```

`padStart(2, "0")` 确保单字节十六进制总是两位（如 `0f` 而不是 `f`），否则拼出的哈希字符串长度不固定，去重逻辑会出错。

---

### 技巧 3：statusCode 附加到 Error 对象

axios 拦截器：

```
const apiError = new Error(message) as Error & { statusCode?: number };
apiError.statusCode = error.response?.status;
return Promise.reject(apiError);
```

TypeScript 的交叉类型 `Error & { statusCode?: number }` 给标准 Error 附加自定义字段，不需要继承新类，调用方可以用 `(err as Error & { statusCode?: number }).statusCode` 判断是否可重试。

---

### 技巧 4：audioRef.current?.load() 强制刷新

重新合成后，URL 不变但文件内容变了：

```
audioRef.current?.load();
```

`<audio>` 元素缓存了旧内容，调用 `load()` 强制浏览器重新请求同 URL，获取新文件。不调用 `load()` 用户会听到旧音频。

---

### 技巧 5：has_synthesis 服务端探测

前端不用 `HEAD /synthesis` 探测文件是否存在（FastAPI 默认不支持 HEAD，会返回 405），而是由 `GET /tasks/{id}/results` 统一返回 `has_synthesis: bool`——服务端用 `Path.exists()` 探测，一次请求包含所有状态。

---

### 技巧 6：>>> 无符号右移实现中点计算

```
const mid = (lo + hi) >>> 1;
```

等价于 `Math.floor((lo + hi) / 2)`，但：
- 避免 `lo + hi` 在极大整数时溢出（JS Number 是 64 位浮点，实际上不溢出，但这是经典写法）
- 比 `Math.floor` 更快（位运算）

---

### 技巧 7：padStart 补零格式化

```
Array.from(new Uint8Array(hashBuffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
```

每个字节转十六进制后必须是两位，`padStart(2, "0")` 在不足两位时左侧补零，保证输出始终是 64 字符的 SHA-256 字符串。

---

### 技巧 8：useMemo 的依赖数组精度

```
const filteredBlocks = useMemo(
  () => blocks.filter((b) => visibleSpeakers.has(b.speaker)),
  [blocks, visibleSpeakers],   // ← 两个都要列出
);
```

依赖数组必须包含 callback 内读取的所有外部变量。漏写 `visibleSpeakers` 会导致过滤器用旧值计算，说话人勾选后列表不更新。

---

### 技巧 9：空值合并（??）与可选链（?.）

```
const message = error.response?.data?.detail ?? error.message ?? "请求失败";
```

`?.` 安全访问深层嵌套对象，任何一级为 null/undefined 时整个表达式返回 undefined，不抛异常。`??` 只在左侧为 null/undefined 时取右侧，与 `||` 不同——`0` 和 `""` 不会触发 `??` 的降级。

---

### 技巧 10：never 类型穷举检查

`types/task.ts` 的 `TaskStatus` 是联合类型，在 switch 语句中可以用 `never` 做穷举检查：

```
function assertNever(x: never): never {
  throw new Error("未处理的状态: " + x);
}

switch (status) {
  case "pending": ...
  case "completed": ...
  default: assertNever(status);   // 遗漏任何一个 case，编译器报错
}
```

**关键文件**：`hooks/useTaskPolling.ts`、`utils/fileHash.ts`、`api/client.ts`、`utils/findBlockIndex.ts`

---

## 第十课：数据流全景

以"用户上传文件 → 看到合成音频"为主线，串联所有知识：

```
用户选择文件（UploadPage.tsx）
    ↓ computeFileSHA256()             ← 技巧 2：Web Crypto SHA-256
    ↓ file.size >= 20MB?
      是 → chunkedUploadFile()        ← 第七课：分片上传
      否 → GET /tasks/lookup?hash=    ← 服务端去重
           POST /tasks/standard_minutes（带 template_id）
    ↓ 返回 task_id
    ↓ navigate(`/workspace/${taskId}`)
    ↓
WorkspacePage.tsx mount
    ↓ getTaskResults()                ← 尝试恢复持久化结果
      ├─ 有结果：写入各 store，status=completed，跳过轮询
      └─ 无结果：setPollEnabled(true) → 启动轮询
    ↓
useTaskPolling（每 2s 轮询）          ← 第四课：自定义 Hook
    ↓ GET /tasks/{id}
    ↓ status === "completed"
      ├─ getTaskResults()             ← 技巧 1：先写 evaluation store
      │   → setHasSynthesis(true)     → synthesisStore
      │   → setEvaluation(...)        → evaluationStore
      └─ setRawEntries(transcript)    → transcriptStore（最后写，触发 SummaryPanel）
    ↓
SummaryPanel useEffect [rawEntries]   ← 第六课：跨组件协调
    → evaluation 已存在 → 跳过自动评估
    → evaluation 不存在 → evaluateText()，长轮询等待结果  ← 第七课：长轮询
    ↓
LeftPanel 检测 hasSynthesis           ← 第六课：受控折叠
    → useEffect → setSynthesisOpen(true)
    ↓
用户点击"合成对话音频"（SynthesisPanel.tsx）
    ↓ POST /tasks/{id}/synthesize
    ↓ 返回 {duration_ms, synthesis_time_ms}
    ↓ setResult(durationMs, synthesisMs)  → synthesisStore
    ↓ audioRef.current?.load()            ← 技巧 4：强制刷新音频缓存
    ↓ 渲染播放器 + 进度条
    ↓
useAudioSync（MediaPlayer）           ← 第四课 + 第八课
    → RAF 每帧同步 currentTime → playerStore
    ↓
useAutoScroll（TranscriptList）       ← 第八课：性能优化
    → findBlockIndex()（二分查找）    ← 技巧 6：>>> 运算符
    → VirtuosoHandle.scrollToIndex()  ← 第八课：虚拟滚动
```

---

## 项目架构全景图

```
┌─────────────────────────────────────────────────────────────┐
│                        React 应用                           │
│                                                             │
│  pages/                                                     │
│    HomePage.tsx        上传入口，路由跳转                   │
│    WorkspacePage.tsx   结果页编排，持久化恢复，轮询协调     │
│                                                             │
│  components/                                                │
│    layout/             AppLayout + LeftPanel + RightPanel   │
│    player/             MediaPlayer（音视频 + 波形）         │
│    transcript/         TranscriptList + TranscriptBlock     │
│    summary/            SummaryPanel（摘要 + 模板选择）      │
│    compliance/         CompliancePanel + ViolationCard      │
│    synthesis/          SynthesisPanel（合成 + 播放控制）    │
│    upload/             UploadPage + UploadProgress          │
│    shared/             ErrorAlert / LoadingSpinner / Toast  │
│                                                             │
│  hooks/                                                     │
│    useTaskPolling      状态机轮询，分发至各 store           │
│    useAudioSync        RAF 时间同步 → playerStore           │
│    useAutoScroll       playerStore 时间 → Virtuoso 滚动     │
│    useAuditKeyboard    合规审核快捷键                       │
│    useExport           PDF / SRT / DOCX 导出                │
│    useWaveSurfer       WaveSurfer.js 波形                   │
│                                                             │
│  stores/               Zustand（无 Provider）               │
│    taskStore           任务状态、轮询开关                   │
│    transcriptStore     原始条目 → mergedBlocks              │
│    evaluationStore     摘要结果、进度                       │
│    complianceStore     合规报告                             │
│    playerStore         currentTime、播放态、媒体元素        │
│    synthesisStore      has_synthesis、时长                  │
│    toastStore          全局通知                             │
│                                                             │
│  api/                  Axios 封装（baseURL=/api/v1）        │
│    client.ts           拦截器，statusCode 附加              │
│    task.ts             submit / status / results / media    │
│    evaluation.ts       evaluateText + 长轮询                │
│    compliance.ts       auditCompliance                      │
│    synthesis.ts        synthesizeTask / getSynthesisAudioUrl│
│    templates.ts        listTemplates                        │
│                                                             │
│  utils/                                                     │
│    chunkedUpload.ts    分片上传（GET query + PATCH chunk）  │
│    fileHash.ts         Web Crypto SHA-256                   │
│    findBlockIndex.ts   二分查找，O(log n)                   │
│    processTranscript.ts rawEntries → MergedBlock[]          │
│    formatTime.ts       毫秒 → MM:SS                         │
│    speakerColor.ts     说话人颜色映射                       │
│    pdfGenerator.ts     jsPDF 导出                           │
│    srtGenerator.ts     SRT 字幕导出                         │
│    wordGenerator.ts    DOCX 导出                            │
│                                                             │
│  types/                TypeScript 类型定义                  │
│    task.ts             TaskStatus / TaskResultsResponse     │
│    transcript.ts       TranscriptEntry                      │
│    evaluation.ts       EvaluationResult（title + content）  │
│    compliance.ts       Violation / ComplianceReport         │
│    view.ts             MergedBlock（UI 展示层）             │
└─────────────────────────────────────────────────────────────┘
```

每一层职责单一：**类型层**定义数据形状，**API 层**负责通信，**Store 层**管理全局状态，**Hook 层**封装副作用逻辑，**组件层**只负责渲染与用户交互。修改 API 响应格式只需改 `types/` 和 `api/`，不需要触碰组件。

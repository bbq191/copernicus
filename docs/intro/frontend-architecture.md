# Copernicus 前端架构文档

> 作者: afu
>
> 本文档基于实际代码梳理，描述前端整体架构、组件层级、状态管理、数据流向及关键设计决策。

---

## 一、技术栈

| 层级 | 技术选型 | 版本 |
|------|---------|------|
| 框架 | React | 19 |
| 语言 | TypeScript | 5.9，严格模式 |
| 构建 | Vite | 7.2（Tailwind 经 @tailwindcss/vite 插件接入）|
| 路由 | React Router（react-router-dom） | v7 |
| 状态管理 | Zustand | v5，无 Provider，函数式 selector |
| 虚拟滚动 | React Virtuoso | 长列表渲染优化 |
| 音频可视化 | WaveSurfer.js | v7，波形渲染 |
| UI 基础 | DaisyUI 5 + TailwindCSS 4 | 主题切换（dark / corporate），主题配置写在 index.css |
| 文件哈希 | hash-wasm | 分块流式 SHA-256（8 MB/块，避免大文件整体读入内存）|
| 文档导出 | docx + jsPDF + html2canvas-pro | SRT / Word / PDF |
| HTTP | Axios | 10 分钟超时，统一拦截器 |

---

## 二、目录结构

```
frontend/src/
  api/              # 后端通信层（Axios 封装 + 轮询逻辑）
    client.ts       #   Axios 实例 + 响应拦截器
    task.ts         #   任务上传/查询/媒体（含 SHA-256 预检）
    evaluation.ts   #   文本评估（内部轮询）
    compliance.ts   #   合规审核（内部轮询）
    synthesis.ts    #   TTS 合成触发 + 状态查询 + 音频 URL
    templates.ts    #   模板列表查询
    health.ts       #   服务健康检查（/health）
  components/       # UI 组件（按功能域分目录）
    layout/         #   三栏布局骨架（含 SynthesisPanel 入口）
    upload/         #   上传与进度（含模板选择）
    player/         #   音视频播放器
    transcript/     #   转写结果展示与编辑
    summary/        #   智能摘要（Markdown 渲染 + 模板选择）
    synthesis/      #   TTS 音频合成与播放
    compliance/     #   合规审核与违规管理
    shared/         #   通用组件（加载、错误、Toast、骨架屏、主题）
  hooks/            # 自定义 Hooks（轮询、同步、滚动、导出、快捷键）
  stores/           # Zustand 状态仓库（7 个独立 store）
  types/            # TypeScript 类型定义
  utils/            # 纯函数工具（时间格式化、聚合、搜索、导出生成）
    chunkedUpload.ts#   分片上传协议实现（断点续传）
    fileHash.ts     #   hash-wasm 分块计算 SHA-256（8 MB/块）
  pages/            # 页面级组件（3 个路由页面）
  App.tsx           # 路由配置入口
  main.tsx          # 应用挂载点
```

---

## 三、路由与页面

应用有三个路由页面，通过 React Router v7 管理：

```
/                       --> HomePage（渲染 UploadPage）
/workspace/:taskId      --> WorkspacePage（核心工作区）
/health                 --> HealthPage（服务健康状态）
```

全局挂载 ToastContainer 通知组件，覆盖所有页面。

### 3.1 HomePage

职责单一，作为 UploadPage 的容器页面，承载文件上传入口。

### 3.2 WorkspacePage

**整个应用的调度中心**，负责三项核心逻辑：

**任务初始化**: 从 URL 参数获取 taskId，初始化 taskStore。

**持久化恢复（优先）**: 挂载时先尝试调用 getTaskResults 恢复历史数据。恢复成功则直接进入 completed 状态，不启动轮询。恢复时若 `has_synthesis = true`，同步写入 synthesisStore 以恢复合成面板状态。

**轮询兜底**: 恢复失败或无历史数据时，设置 pollEnabled = true 启动轮询。

**条件渲染逻辑**:

```
taskId 存在？
  ├── 否 → 空白
  └── 是 → status 判断
        ├── failed → ErrorAlert 错误提示
        ├── 处理中 → UploadProgress 流水线进度
        ├── 未初始化 → WorkspaceSkeleton 骨架屏
        └── completed → AppLayout 主工作区
```

### 3.3 HealthPage

服务健康状态页面，入口位于首页和工作区 Navbar。调用 `GET /api/v1/health`，以 10 秒间隔自动刷新，展示：

- ASR / LLM / TTS 三个组件的状态（ok / degraded / down）与详情
- 任务队列统计（进行中 / 已完成 / 失败 / 合成中）
- VRAM 水位（已加载模型列表、估算占用、预算上限）

---

## 四、布局架构

AppLayout 采用**固定三栏布局**，顶部 Navbar 贯穿全宽：

```
+------------------------------------------------------------------+
|  Navbar（品牌标识 + 主题切换 ThemeToggle）                          |
+----------------+----------------------------+--------------------+
|  左栏 420px     |  中栏 flex-1（自适应）       |  右栏 380px        |
|  overflow-y-auto|  (主工作区)                 |  (条件渲染)         |
|                |                            |                    |
|  MediaPlayer   |  Tab: 转写结果              | EvidenceDetail-   |
|  (音视频播放)   |    TranscriptToolbar       | Panel             |
|                |    TranscriptList          | (违规证据详情)      |
|  SummaryPanel  |    (Virtuoso 虚拟滚动)      |                    |
|  (智能摘要)     |                            |                    |
|  [可折叠]       |  Tab: 违规报告              |                    |
|                |    ViolationList           |                    |
|  SynthesisPanel|    (过滤/搜索/批量操作)      |                    |
|  (TTS 音频)     |                            |                    |
|  [可折叠，受控]  |                            |                    |
|                |                            |                    |
|  Compliance-   |                            |                    |
|  Panel         |                            |                    |
|  (合规配置)     |                            |                    |
|  [可折叠]       |                            |                    |
+----------------+----------------------------+--------------------+
```

**左栏（LeftPanel）**: 垂直堆叠四个面板——播放器、智能摘要（可折叠）、TTS 合成（可折叠，受控组件）、合规配置（可折叠）。左栏自身可滚动（`overflow-y-auto`），内容超长时不裁剪。

**中栏（RightPanel）**: 双标签页切换。"转写结果"标签页包含工具栏和虚拟滚动列表；"违规报告"标签页在有合规报告时出现，包含完整的违规审核工作台。

**右栏（EvidenceDetailPanel）**: 条件渲染的抽屉式面板，仅在用户点击违规卡片的"详情"按钮时展开，展示完整证据信息。

---

## 五、组件层级

### 5.1 上传模块

```
UploadPage
  ├── 模板选择下拉（从 listTemplates() 加载，> 1 个模板时显示）
  └── 拖拽区域 / 点击选择
        ↓ 1. computeFileSHA256(file)          本地计算 SHA-256，无网络请求
        ↓ 2. GET /tasks/lookup?hash=...        预检：是否已有该文件的任务
        │     ├── 200 existing → 直接跳转，跳过上传
        │     └── 404         → 继续上传
        ↓ 3. 文件大小判断
        │     ├── < 20 MB → POST /tasks/standard_minutes（普通上传，含重试）
        │     └── ≥ 20 MB → chunkedUploadFile（分片上传，断点续传）
        ↓ 上传中：显示 spinner（uploading 状态）
        ↓ 完成：navigate(/workspace/:taskId)

UploadProgress
  └── 流水线步骤可视化
        ├── 语音识别（processing_asr）
        ├── 关键帧提取（extracting_frames）
        ├── 视觉扫描（scanning_visual）
        ├── 文本纠正（correcting）
        ├── 内容评估（evaluating）
        └── 合规审核（auditing）
```

**分片上传**: 文件 ≥ 20MB 时使用 `chunkedUploadFile`，5MB 为单片大小。先 GET 查询已有会话（断点续传），再按序 PATCH 上传各分块，携带 `Content-Range` 头。全部分块上传完毕后，服务端自动触发流水线。

**普通上传**: 预检未命中时发起 POST，网络抖动失败时自动重试（指数退避，最多 3 次），4xx 业务错误不重试。

### 5.2 播放器模块

```
MediaPlayer
  ├── [mediaType=video] <video> 元素
  ├── [mediaType=audio] <audio> 元素 + WaveformDisplay
  ├── ProgressBar（进度条 + 违规标记点）
  └── PlaybackControls（播放/倍速/音量/循环）
```

**双模式切换**: 根据 playerStore.mediaType 自动选择 video 元素或 audio + 波形图组合。

**WaveformDisplay**: 为 WaveSurfer.js 提供挂载容器，仅音频模式下初始化。

**ProgressBar**: 除基础进度拖拽外，还渲染合规违规标记点（颜色按严重程度区分），悬浮显示违规原因，点击跳转到违规前 5 秒。

**PlaybackControls**: 播放/暂停、倍速（0.5x-2x）、音量滑块、循环播放开关（仅当 loopRegion 存在时显示）。

### 5.3 转写模块

```
TranscriptToolbar
  ├── 文本模式切换（原文 / 修正文）
  ├── 说话人重命名按钮
  ├── 重新转写按钮
  ├── 导出下拉菜单（SRT / Word / PDF）
  ├── 全文搜索输入框
  └── 说话人显隐筛选（多人时显示）

TranscriptList（Virtuoso 虚拟滚动）
  └── TranscriptBlock（聊天气泡）
        ├── SpeakerAvatar（头像 + 颜色哈希）
        ├── 说话人名称 + 时间戳
        └── SentenceSpan（句子级）
              ├── 细粒度时间标签
              ├── 点击跳转播放
              ├── 当前播放高亮
              └── 搜索关键词高亮

SpeakerRenameModal
  └── 批量重命名说话人（spk_0 → 实际姓名）
```

**虚拟滚动**: TranscriptList 基于 React Virtuoso 实现，处理数千条转写记录无压力。数据源为 transcriptStore.mergedBlocks 经说话人筛选后的 filteredBlocks。

**聊天气泡**: TranscriptBlock 按说话人奇偶 ID 左右交替排列，当前播放块带高亮边框。

**句子级交互**: SentenceSpan 每个句子独立显示时间标签，点击即跳转播放器到对应时间点，搜索关键词实时高亮。

### 5.4 智能摘要模块

```
SummaryPanel
  ├── 模板选择下拉（从 listTemplates() 加载，> 1 个模板时显示）
  ├── 自动评估触发（转写完成后，跳过已有 evaluation 时）
  ├── 轮询进度显示
  ├── 重新评估按钮
  └── 纪要内容展示
        ├── evaluation.title（纪要标题）
        └── evaluation.formatted_content（Markdown 纪要正文，whitespace-pre-wrap）
```

SummaryPanel 监听 rawEntries 变化，首次有数据且 evaluationStore 中无 evaluation 时自动调用 `evaluateText` 发起评估，使用当前选中的 templateId。评估采用内部轮询模式，进度实时更新到 evaluationStore。完成后展示 `title` 和 `formatted_content`。支持手动选择模板后触发重新评估。

**模板选择**: 下拉仅在 templates.length > 1 时显示，默认 templateId 为 "universal"。`evaluateText` 将 templateId 作为 FormData 字段发送到后端。

### 5.5 TTS 音频重塑模块

```
SynthesisPanel
  ├── [hasSynthesis=true] 音频播放器
  │     ├── <audio> 元素（隐藏，ref 控制）
  │     ├── 播放/暂停按钮（图标切换）
  │     ├── 进度滑块（range input）
  │     ├── 时间显示（当前/总时长）
  │     └── 下载 MP3 链接
  ├── 合成/重新合成按钮
  └── 说明文字（未合成时显示）
```

**状态来源**: `hasSynthesis` 来自 `synthesisStore`（Zustand），不用本地 state，跨组件共享。

**播放器**: 使用隐藏 `<audio>` 元素 + 自定义控件，`audioRef.current?.load()` 强制浏览器重新加载同名 URL 的新内容（重新合成场景）。

**合成触发（异步）**: 调用 `POST /tasks/{taskId}/synthesize` 后服务端立即返回 202，合成在后台执行（ModelManager 互斥锁保护下卸载 ASR → 加载 TTS → 合成 → 写入 synthesis.mp3）。面板以 2 秒间隔轮询 `GET /tasks/{taskId}/synthesis/status`，直到 completed / failed。页面刷新后挂载时先查一次状态，恢复已有合成结果。

### 5.6 合规审核模块

```
CompliancePanel（左栏配置面板）
  ├── 规则文件上传区（CSV / XLSX，拖拽或点击）
  ├── 合规分数环形进度条
  ├── 违规分级统计（高 / 中 / 低）
  ├── AI 审核摘要
  └── 重新审核按钮

ViolationList（中栏违规工作台）
  ├── 统计仪表板（高风险 / 疑似 / 待审 / 合规度）
  ├── 快捷键提示卡（可关闭，localStorage 持久记忆）
  ├── 三级筛选工具栏
  │     ├── 严重程度（全部 / 高 / 中 / 低）
  │     ├── 来源（全部 / 语音 / OCR / 视觉）
  │     └── 状态（全部 / 待审 / 已确认 / 已忽略）
  ├── 搜索框（匹配违规原因 / 原文 / 规则 / 证据文本）
  ├── 批量模式切换
  └── ViolationCard 列表
        ├── 徽章行（时间戳 / 来源 / 严重程度 / 说话人 / 状态 / 置信度）
        ├── 违规原因
        ├── AI 判定逻辑（CoT 推理链，可折叠）
        ├── EvidenceBlock（按来源分策略渲染）
        │     ├── [transcript] 原文引用
        │     ├── [ocr] OCR 文本 + 截图缩略图
        │     └── [vision] 截图 + 描述文本
        ├── 规则引用（tooltip 显示完整内容）
        └── 操作按钮（确认违规 / 误报忽略 / 重新审核）

EvidenceDetailPanel（右栏抽屉面板，380px）
  ├── 完整证据展示
  │     ├── 来源 + 时间戳（可跳转）+ 说话人 + 置信度
  │     ├── 违规原因
  │     ├── AI 判定逻辑（分步展示）
  │     ├── 证据截图（支持缩放查看）
  │     ├── OCR 完整文本
  │     ├── 原始文本引用
  │     ├── 规则详细内容
  │     └── 转录上下文（前后 3 条，当前高亮）
  └── 操作按钮（确认 / 忽略 / 重新审核）
```

### 5.7 通用组件

| 组件 | 职责 |
|------|------|
| LoadingSpinner | 加载动画 |
| ThemeToggle | dark / corporate 主题切换 |
| ErrorAlert | 错误提示，显示 taskStore.error |
| ToastContainer | 右下角通知容器，最多 3 条，3 秒自动消失 |
| WorkspaceSkeleton | 工作区骨架屏，任务初始化中展示 |

---

## 六、状态管理

采用 Zustand 函数式 store，7 个独立仓库各司其职，无全局 Provider 包装。组件通过 selector 精确订阅所需字段，避免无关渲染。

### 6.1 Store 全景

```
taskStore          任务生命周期（taskId / status / progress / pollEnabled）
playerStore        播放器状态（currentTime / duration / mediaSrc / loopRegion）
transcriptStore    转写数据（rawEntries / mergedBlocks / speakerMap / textMode）
evaluationStore    评估结果（evaluation / progress / loading）
synthesisStore     TTS 合成状态（hasSynthesis / durationMs / synthesisMs）
complianceStore    合规审核（report / filters / batchMode / evidencePanel）
toastStore         通知消息（toasts 队列）
```

### 6.2 taskStore

管理任务全生命周期状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| taskId | string / null | 当前任务 ID |
| status | TaskStatus / null | 任务状态枚举 |
| progress | TaskProgress | 进度（current_chunk / total_chunks / percent）|
| error | string / null | 错误消息 |
| pollEnabled | boolean | 轮询开关 |
| isVideoTask | boolean | 是否视频任务（由 extracting_frames / scanning_visual 阶段推断）|

**关键决策**: pollEnabled 必须在 taskStore 中，不能用 WorkspacePage 的 local state，因为 useTaskPolling 需要稳定引用。

### 6.3 playerStore

管理音视频播放器的全部状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| mediaSrc | string / null | 媒体 URL |
| mediaElement | HTMLMediaElement / null | DOM 元素引用 |
| mediaType | "audio" / "video" | 媒体类型（多模态切换）|
| currentTime | number | 当前播放时间（毫秒）|
| duration | number | 总时长（毫秒）|
| isPlaying | boolean | 播放状态 |
| playbackRate | number | 倍速 |
| volume | number | 音量 |
| loopEnabled | boolean | 循环开关 |
| loopRegion | object / null | 循环区间（startMs / endMs）|

**核心方法**: seekAndPlay(ms) 供违规卡片点击跳转使用，同时设置 loopRegion 实现违规片段循环。

### 6.4 transcriptStore

管理转写数据和前端视图聚合。

| 字段 | 类型 | 说明 |
|------|------|------|
| rawEntries | TranscriptEntry[] | 后端原始转写条目 |
| mergedBlocks | MergedBlock[] | 前端聚合视图（同说话人 30s 内合并）|
| speakerMap | Record | 说话人重命名映射 |
| textMode | "original" / "corrected" | 显示模式 |
| editedTexts | Record | 用户在线编辑的文本（blockId:idx → 文本）|
| searchQuery | string | 搜索关键词 |
| visibleSpeakers | Set | 可见说话人集合 |

**聚合逻辑**: setRawEntries 写入原始数据后自动调用 processTranscriptForView，将连续相同说话人且间隔小于 30 秒的条目合并为 MergedBlock。

### 6.5 evaluationStore

管理智能评估的结果和进度。

| 字段 | 类型 | 说明 |
|------|------|------|
| evaluation | EvaluationResult / null | 评估结果（title + formatted_content）|
| isLoading | boolean | 加载状态 |
| progress | number | 进度百分比（0-100）|
| progressText | string | 进度描述（"生成摘要中..."）|
| error | string / null | 错误消息 |

### 6.6 synthesisStore

管理 TTS 合成状态，在 SynthesisPanel 和 LeftPanel 间共享。

| 字段 | 类型 | 说明 |
|------|------|------|
| hasSynthesis | boolean | 是否已有合成音频 |
| durationMs | number / null | 合成音频时长（毫秒）|
| synthesisMs | number / null | 合成耗时（毫秒）|

**初始化**: WorkspacePage 挂载时从 `getTaskResults` 读取 `has_synthesis`，若为 true 则调用 `setHasSynthesis(true)`。轮询完成时同步读取 `results.has_synthesis`。

### 6.7 complianceStore

最复杂的 store，管理合规审核全流程。

**核心状态**:

| 字段 | 类型 | 说明 |
|------|------|------|
| report | ComplianceReport / null | 合规报告 |
| rules | ComplianceRule[] / null | 规则列表 |
| selectedViolation | Violation / null | 当前选中违规 |
| selectedIndex | number | 过滤后索引（导航用）|
| severityFilter | string | 严重程度过滤 |
| statusFilter | string | 状态过滤 |
| sourceFilter | string | 来源过滤（多模态）|
| searchQuery | string | 搜索关键词 |
| batchMode | boolean | 批量操作模式 |
| selectedIds | Set | 批量选中的违规 ID 集合 |
| evidenceDetail | Violation / null | 证据详情面板数据 |
| evidencePanelOpen | boolean | 证据详情面板开关 |

**多维过滤**: 辅助函数 getFilteredViolations 对违规列表依次应用严重程度、来源、状态、搜索关键词四层过滤。

**防抖持久化**: setViolationStatus 修改违规状态后，内部调用 schedulePersist 聚合 500ms 内的变更，批量调用后端 PATCH 接口持久化。

### 6.8 toastStore

轻量通知队列，最多保留 3 条消息，每条默认 3 秒后自动移除。

---

## 七、自定义 Hooks

### 7.1 useTaskPolling

接受 enabled 参数，以 2 秒间隔轮询 getTaskStatus。

**竞态修复**: 任务完成时的操作顺序至关重要——先 `await getTaskResults()` 写入 evaluation / synthesis / video 状态到各 store，再调用 `setRawEntries` 触发 SummaryPanel 的自动评估 effect。这确保 SummaryPanel 看到已有 evaluation 时不会用默认模板重复提交评估。

```
completed 时执行顺序:
  1. await getTaskResults()
     ├── results.has_video → playerStore.setMediaSrc("video")
     ├── results.has_synthesis → synthesisStore.setHasSynthesis(true)
     └── results.evaluation → evaluationStore.setEvaluation(...)
  2. setRawEntries(transcript)  ← 触发 SummaryPanel effect 时 evaluation 已写入
```

### 7.2 useAudioSync

接受 mediaRef 引用，监听 HTML Media Element 的 loadedmetadata / play / pause / ended 事件，通过 requestAnimationFrame 循环（50ms 节流）将 currentTime 同步到 playerStore。同时检测循环播放：当 loopEnabled 且 currentTime 超过 loopRegion.endMs 时自动跳转到 startMs。

### 7.3 useWaveSurfer

接受容器 ref 和音频元素 ref，创建 WaveSurfer 实例（紫色渐变波形，高度 80px）。仅音频模式下初始化，mediaSrc 变化时销毁重建。

### 7.4 useAutoScroll

接受 Virtuoso ref 和 blocks 数组，监听 playerStore.currentTime 变化，通过 findBlockIndex 二分查找当前播放块索引，调用 scrollToIndex 滚动到视口中心。首次挂载时通过 rAF + 150ms setTimeout 延迟重试，确保 Virtuoso 初始化完成。

**关键约束**: blocks 参数必须与 Virtuoso 的 data 属性使用同一数组引用（filteredBlocks），否则索引错位。

### 7.5 useExport

返回 isExporting 状态和 exportAs 方法，统一封装 SRT / Word / PDF 三种导出格式，成功或失败通过 Toast 通知用户。

### 7.6 useAuditKeyboard

接受 enabled 参数，注册违规审核专用键盘快捷键：

| 按键 | 功能 |
|------|------|
| Space | 播放/暂停 |
| Enter | 确认当前违规 |
| Delete / Backspace | 标记误报忽略 |
| 上/下箭头 | 导航上/下一条违规，自动跳转播放 |
| B | 切换批量操作模式 |
| Ctrl+A | 批量模式下全选 |
| Esc | 关闭证据详情面板或退出批量模式 |

智能过滤：焦点在 INPUT / TEXTAREA / contentEditable 元素时不拦截按键。

---

## 八、API 通信层

### 8.1 基础客户端

Axios 实例，baseURL 为 `/api/v1`，超时 10 分钟（适应长时间 ASR 处理）。响应拦截器统一提取 `error.response.data.detail` 或 `error.message` 作为 Error 消息，同时将 HTTP 状态码附加到 Error 对象的 `statusCode` 属性上。网络错误（无响应）的 `statusCode` 为 undefined，上层重试逻辑通过此字段区分网络错误与业务错误。

### 8.2 API 模块划分

| 模块 | 核心函数 | 说明 |
|------|---------|------|
| task.ts | submitStandardMinutesTask | 本地计算 SHA-256 → 预检 → 普通上传或分片上传 |
| | getTaskStatus | 轮询任务状态 |
| | getTaskResults | 获取完整持久化结果（含 has_synthesis）|
| | rerunTranscript | 重新转写 |
| | getTaskMediaUrl | 生成媒体文件 URL |
| | getFrameUrl | 生成关键帧图片 URL |
| | resolveEvidenceUrl | 解析证据 URL（兼容多种路径格式）|
| evaluation.ts | evaluateText | 提交评估（含 templateId）+ 内部轮询至完成 |
| compliance.ts | auditCompliance | 提交合规审核 + 内部轮询至完成 |
| | persistViolationStatuses | 批量持久化违规状态 |
| synthesis.ts | startSynthesis | 触发 TTS 合成（202 异步）|
| | getSynthesisStatus | 轮询合成状态（running / completed / failed）|
| | getSynthesisAudioUrl | 生成合成音频 URL（/tasks/{id}/synthesis）|
| templates.ts | listTemplates | 获取可用纪要模板列表（id / name / description）|
| health.ts | getHealth | 服务健康检查（组件状态 + 任务统计 + VRAM 水位）|
| utils/fileHash.ts | computeFileSHA256 | hash-wasm 分块计算文件 SHA-256（8 MB/块，大文件不整体读入内存）|
| utils/chunkedUpload.ts | chunkedUploadFile | 分片上传实现（5MB/片，断点续传，带进度回调）|

### 8.3 轮询模式

评估和合规 API 均采用**内部轮询模式**：提交异步任务后，API 函数内部以 2 秒间隔轮询任务状态，期间通过 store 上报进度，最终返回完整结果。调用方无需关心轮询细节。

---

## 九、类型系统

### 9.1 核心类型关系

```
TaskStatus（枚举）
  pending | processing_asr | extracting_frames | scanning_visual
  | correcting | evaluating | auditing | completed | failed

TranscriptEntry（转写条目）
  timestamp_ms / end_ms / speaker / text / text_corrected

MergedBlock（前端聚合视图）
  id / speaker / startMs / endMs / sentences: TranscriptEntry[]

EvaluationResult（评估结果，对应后端 schema）
  title: string          -- 纪要标题
  formatted_content: string  -- Markdown 格式纪要正文

Violation（违规记录）
  通用: rule_id / rule_content / reason / severity / confidence / status
  来源: source(transcript/ocr/vision) / evidence_url / evidence_text
  认知: reasoning（CoT 推理链）
  定位: timestamp_ms / end_ms / speaker / original_text

ComplianceReport
  violations[] + summary + compliance_score + total_rules

TaskResultsResponse
  task_id / transcript / evaluation / compliance
  has_audio / has_video / has_synthesis / keyframe_count / ...
```

### 9.2 多模态类型

| 类型 | 字段 | 用途 |
|------|------|------|
| OCRRecord | timestamp_ms / text / confidence / frame_path / bbox | OCR 扫描结果 |
| VisualEvent | event_type / start_ms / end_ms / confidence / frame_path | 人脸检测事件 |
| ViolationSource | "transcript" / "ocr" / "vision" | 违规来源标识 |

---

## 十、数据流向

### 10.1 上传到转写

```
UploadPage
  ↓ computeFileSHA256(file)              本地计算 SHA-256
  ↓ GET /tasks/lookup?hash=...           预检
  ├── 命中（existing=true）→ 直接获得 task_id，跳过上传
  └── 未命中 → 文件大小判断
        ├── < 20MB → POST /tasks/standard_minutes（含 templateId，最多重试 3 次）
        └── ≥ 20MB → chunkedUploadFile（断点续传，含进度回调）
  ↓ 获得 task_id
  ↓ navigate(/workspace/:taskId)
WorkspacePage
  ↓ 尝试 getTaskResults（持久化恢复）
  │     ├── has_synthesis=true → synthesisStore.setHasSynthesis(true)
  │     └── has_video=true → playerStore.setMediaSrc("video")
  ↓ 失败 → setPollEnabled(true)
  ↓ useTaskPolling 启动
  ↓ 2s 轮询 getTaskStatus
  ↓ completed:
      1. await getTaskResults → 写入 evaluation/synthesis/video 到 store
      2. setRawEntries → 触发 SummaryPanel effect（此时 evaluation 已写入）
  ↓ 渲染 AppLayout
```

### 10.2 播放器与转写同步

```
MediaPlayer
  ↓ useAudioSync 监听 media element
  ↓ rAF 循环更新 playerStore.currentTime
TranscriptList
  ↓ useAutoScroll 监听 currentTime
  ↓ findBlockIndex 二分查找当前块
  ↓ Virtuoso scrollToIndex 滚动到视口中心
SentenceSpan
  ↓ 用户点击句子
  ↓ playerStore.seekAndPlay(timestamp_ms)
  ↓ 播放器跳转
```

### 10.3 转写到评估

```
SummaryPanel
  ↓ 监听 rawEntries 变化
  ↓ rawEntries.length > 0 且 evaluationStore.evaluation === null
  ↓ evaluateText(fullText, taskId, templateId)
  ↓ API 内部轮询，进度更新到 evaluationStore
  ↓ 完成 → setEvaluation({ title, formatted_content })
  ↓ 渲染 evaluation.title + evaluation.formatted_content（Markdown）
```

### 10.4 TTS 音频合成

```
SynthesisPanel
  ↓ 用户点击"合成对话音频"
  ↓ startSynthesis(taskId)       POST /tasks/{id}/synthesize → 202 { status: running }
  ↓ 2s 间隔轮询 GET /tasks/{id}/synthesis/status（服务端 ChatTTS 后台合成，ModelManager 保证互斥）
  ↓ status=completed → 返回 { duration_ms, synthesis_time_ms }
  ↓ synthesisStore.setResult(...)
  ↓ audioRef.current?.load()     强制浏览器重新加载 synthesis.mp3
  ↓ LeftPanel useEffect 检测 hasSynthesis=true → 自动展开合成面板
```

### 10.5 转写到合规审核

```
CompliancePanel
  ↓ 用户上传规则文件
  ↓ auditCompliance(rawEntries, rulesFile, taskId)
  ↓ API 内部轮询，进度更新到 complianceStore
  ↓ 完成 → setReport
  ↓ RightPanel 切换到违规标签页
  ↓ ViolationList 渲染违规卡片
```

### 10.6 违规审核到持久化

```
ViolationCard / useAuditKeyboard
  ↓ setViolationStatus(violation, "confirmed" | "rejected")
  ↓ complianceStore 内部 schedulePersist
  ↓ 500ms 防抖聚合
  ↓ persistViolationStatuses(taskId, updates[])
  ↓ 后端 PATCH 持久化到 JSON 文件
```

### 10.7 违规跳转播放

```
ViolationCard 时间戳点击
  ↓ setLoopRegion(timestamp_ms - 5000, end_ms + 10000)
  ↓ seekAndPlay(timestamp_ms - 5000)
  ↓ 播放器跳转并循环播放违规片段
  ↓ useAudioSync 检测循环边界自动回跳
```

---

## 十一、关键设计决策

### 11.1 轮询竞态保护

**评估竞态问题**: SummaryPanel 监听 rawEntries，首次有数据时触发自动评估。如果 setRawEntries 在 getTaskResults 之前执行，SummaryPanel 看到 evaluation 为 null，会立即用默认模板提交评估，忽略用户在上传时选择的模板。

**修复方案**: useTaskPolling 中在 completed 时，先 `await getTaskResults()` 将 evaluation 写入 evaluationStore，再调用 `setRawEntries()`。SummaryPanel effect 检查 evaluationStore.evaluation 非空时跳过自动触发。

**持久化恢复顺序**: WorkspacePage 挂载时恢复数据，必须先设置 evaluationStore、synthesisStore 和 complianceStore 的数据，再将 status 设为 completed。否则 SummaryPanel 挂载时读到空 evaluation 会发起重复评估。

### 11.2 受控 Collapse 与合成面板

DaisyUI collapse 组件的 `defaultChecked` 属性只在首次渲染时生效，无法响应后续状态变化。SynthesisPanel 在合成完成后需要自动展开，因此 LeftPanel 中的合成折叠面板使用**受控模式**：`checked={synthesisOpen}` + `onChange` 回调，并通过 `useEffect` 监听 `hasSynthesis` 变为 true 时自动设置 `setSynthesisOpen(true)`。

### 11.3 has_synthesis 服务端检测

早期实现使用前端 `fetch(getSynthesisAudioUrl(taskId), { method: "HEAD" })` 探测合成文件是否存在，但 FastAPI 的 FileResponse 路由不自动处理 HEAD 请求，返回 405。此外，synthesis.mp3 可能被生命周期服务清理。

**改为服务端检测**: 后端 `GET /tasks/{id}/results` 返回 `has_synthesis: bool`，由服务端实时检测 `synthesis.mp3` 是否存在。前端直接读取该字段，无需额外 HTTP 探测。

### 11.4 pollEnabled 归属

轮询开关放在 taskStore 而非页面 local state，确保 useTaskPolling 拿到稳定引用，避免闭包导致的轮询失控。

### 11.5 性能优化

**Virtuoso 虚拟滚动**: 仅渲染视口内的转写块，处理数千条记录不卡顿。

**rAF 节流同步**: useAudioSync 通过 requestAnimationFrame 循环同步播放时间，50ms 节流避免过频更新。

**useMemo 缓存**: filteredBlocks 等计算结果通过 useMemo 缓存，说话人筛选变化时才重算。

**防抖持久化**: 违规状态变更 500ms 聚合后批量提交，避免逐条发请求。

### 11.6 用户体验

**自动滚动延迟重试**: Virtuoso 首次挂载时 scrollToIndex 可能失效，通过 rAF + 150ms setTimeout 两次重试确保定位成功。

**违规循环播放**: 点击违规卡片自动设置循环区间（前 5 秒到后 10 秒），便于反复听取违规片段。

**键盘驱动审核**: 专业审核员可全程键盘操作——上下导航、Enter 确认、Delete 忽略、Space 播放——无需频繁移动鼠标。

**快捷键提示持久化**: 快捷键帮助卡片关闭后通过 localStorage 记住，不再重复显示。

### 11.7 证据 URL 兼容

resolveEvidenceUrl 函数兼容三种路径格式：http/api 开头直接使用、绝对路径提取文件名转 API 路径、纯文件名通过 getFrameUrl 拼接。确保后端路径格式变化不影响前端渲染。

---

## 十二、工具函数

| 函数 | 位置 | 职责 |
|------|------|------|
| formatTime | utils/formatTime.ts | 毫秒转 MM:SS 或 HH:MM:SS |
| formatTimeSrt | utils/formatTime.ts | 毫秒转 SRT 时间格式 HH:MM:SS,mmm |
| processTranscriptForView | utils/processTranscript.ts | 同说话人 30s 内合并为 MergedBlock |
| findBlockIndex | utils/findBlockIndex.ts | 二分查找当前播放时间对应的块索引 |
| getSpeakerBgColor / getSpeakerTextColor | utils/speakerColor.ts | 说话人颜色哈希映射 |
| getSpeakerInitial | utils/speakerColor.ts | 提取说话人首字母 |
| generateSrt / downloadSrt | utils/srtGenerator.ts | 生成 SRT 内容并触发浏览器下载 |
| exportToWord | utils/wordGenerator.ts | 导出 Word 文档（docx 库 + file-saver）|
| exportToPdf | utils/pdfGenerator.ts | 导出 PDF（html2canvas-pro + jsPDF，支持分页）|
| computeFileSHA256 | utils/fileHash.ts | hash-wasm 分块计算文件 SHA-256（8 MB/块）|
| chunkedUploadFile | utils/chunkedUpload.ts | 分片上传协议（断点续传，5MB/片）|

---

## 十三、接口调用示例

本节描述后端 HTTP 接口的调用格式与响应结构，适用于三方系统集成。所有接口 baseURL 为 `/api/v1`。

---

### 13.1 上传前预检（避免重复传输）

在发起上传之前，先将文件内容计算 SHA-256，通过预检接口查询是否已有该文件的处理记录。

```
GET /api/v1/tasks/lookup?hash={sha256_hex}
```

**命中（已有任务）**

```
HTTP 200
{
  "task_id": "a3f8c1d2...",
  "status": "completed",
  "existing": true
}
```

命中时可直接跳转到工作区轮询结果，无需上传文件。status 可能为任意 TaskStatus 值（含处理中状态）。

**未命中**

```
HTTP 404
{ "detail": "Task not found" }
```

未命中时继续执行上传流程。

---

### 13.2 提交标准纪要任务（主入口）

```
POST /api/v1/tasks/standard_minutes
Content-Type: multipart/form-data

file:             <音视频文件二进制>
hotwords:         （可选）JSON 数组字符串，如 ["公司名", "产品名"]
visual_scan:      （可选）"true" 启用视觉扫描（关键帧+OCR+人脸检测）
generate_summary: （可选）"false" 跳过摘要生成，默认 true
template_id:      （可选）纪要模板 ID，默认 "universal"
```

**响应（202 Accepted）**

```
{
  "task_id": "a3f8c1d2...",
  "status": "pending",
  "existing": false
}
```

---

### 13.3 分片上传（大文件）

**第一步：查询或创建会话**

```
GET /api/v1/uploads/{sha256_hex}?filename=meeting.mp4&total_size=104857600
```

响应返回已接收字节数，续传时可从断点继续。

**第二步：上传数据块**

```
PATCH /api/v1/uploads/{sha256_hex}
Content-Range: bytes 0-5242879/104857600
Content-Type: application/octet-stream

<5MB 原始字节>
```

所有分块上传完毕后，服务端自动触发 standard_minutes 流水线，响应返回 task_id。

---

### 13.4 查询任务状态（轮询）

```
GET /api/v1/tasks/{task_id}
```

**响应**

```
{
  "task_id": "a3f8c1d2...",
  "status": "correcting",
  "progress": {
    "current_chunk": 3,
    "total_chunks": 10,
    "percent": 41.0
  },
  "result": null,
  "error": null
}
```

建议轮询间隔 2 秒。status 枚举值：

| 值 | 含义 |
|---|---|
| pending | 等待处理 |
| processing_asr | 语音识别中 |
| extracting_frames | 提取视频关键帧 |
| scanning_visual | OCR + 人脸检测 |
| correcting | 四阶段文本纠正 |
| evaluating | 内容评估 |
| auditing | 合规审核 |
| completed | 全部完成 |
| failed | 处理失败（error 字段含原因）|

---

### 13.5 获取完整结果

任务 completed 后，通过此接口一次性获取所有持久化结果。

```
GET /api/v1/tasks/{task_id}/results
```

**响应结构**

```
{
  "task_id": "a3f8c1d2...",
  "transcript": {
    "transcript": [
      {
        "timestamp":    "00:00:01",
        "timestamp_ms": 1200,
        "end_ms":       3800,
        "speaker":      "spk_0",
        "text":         "原始识别文本",
        "text_corrected": "纠正后文本"
      }
    ],
    "processing_time_ms": 12400
  },
  "evaluation": {
    "title": "产品发布会议纪要",
    "formatted_content": "## 会议概述\n..."
  },
  "compliance": { ... },
  "has_audio": true,
  "has_video": false,
  "has_synthesis": false,
  "keyframe_count": 0,
  "ocr_text_count": 0,
  "visual_event_count": 0
}
```

evaluation 和 compliance 在对应任务未完成时为 null。`has_synthesis` 由服务端实时检测 synthesis.mp3 是否存在。

---

### 13.6 获取媒体文件

```
GET /api/v1/tasks/{task_id}/media
```

返回原始上传的音频或视频文件（FileResponse），Content-Type 由文件扩展名推断。视频优先，其次音频。

---

### 13.7 TTS 音频合成

```
POST /api/v1/tasks/{task_id}/synthesize
Content-Type: application/json（可选）

{
  "voice_map": { "spk_0": "42", "spk_1": "7" }
}
```

服务端通过 ModelManager 互斥卸载 ASR → 加载 ChatTTS → 合成对话音频 → 保存为 synthesis.mp3。

**响应**

```
{
  "audio_url": "/api/v1/tasks/a3f8c1d2.../synthesis",
  "duration_ms": 183000,
  "synthesis_time_ms": 24500
}
```

合成完成后通过 `GET /api/v1/tasks/{task_id}/synthesis` 下载 MP3 文件。

---

### 13.8 重新转写（不重传文件）

```
POST /api/v1/tasks/{task_id}/rerun-transcript
Content-Type: multipart/form-data

hotwords: （可选）新的热词列表
```

服务端从磁盘读取已持久化的原始音频，重新执行 ASR 和纠正流程。同时清除该任务已有的 evaluation 和 compliance 结果。

**响应（200）**

```
{
  "task_id": "a3f8c1d2...",
  "status": "pending",
  "existing": false
}
```

---

### 13.9 三方系统集成建议

三方系统调用时的推荐流程：

```
1. 本地计算文件 SHA-256

2. GET /tasks/lookup?hash={sha256}
   ├── 200 → 记录 task_id，跳至第 5 步
   └── 404 → 继续

3. 提交文件
   ├── < 20MB → POST /tasks/standard_minutes（上传文件，含 template_id）
   └── ≥ 20MB → 分片上传（GET /uploads/{hash} 创建会话 + PATCH 上传分块）
   ├── 成功 → 记录 task_id
   └── 网络错误 / 5xx → 重试（最多 3 次，间隔 2/4/8 秒）
       重试时再次调 lookup，防止上次传输已在后台处理

4. 若所有重试均失败 → 上报错误，人工介入

5. 以 2 秒间隔轮询 GET /tasks/{task_id}
   ├── status = completed → 调 GET /tasks/{task_id}/results 获取结果
   └── status = failed    → 读取 error 字段，决定是否重新转写
```

关键保证：SHA-256 去重在服务端幂等执行，同一文件无论上传多少次，服务端只保留一份处理结果。

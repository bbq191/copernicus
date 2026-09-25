# Copernicus 后端架构文档

> 作者: afu
>
> 本文档基于实际代码梳理，描述后端整体架构、服务层设计、Pipeline 编排、LLM 集成及关键设计决策。

---

## 一、技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| Web 框架 | FastAPI | 异步路由 + Lifespan 生命周期 |
| 配置 | pydantic-settings | .env 文件驱动，类型安全 |
| ASR 引擎 | FunASR (Paraformer / SenseVoice) | 双模式语音识别 + 说话人分离 |
| LLM | Ollama 本地 / OpenAI 兼容云端（DeepSeek、vLLM 等）| httpx 直连，流式响应，无官方 SDK；由 `LLM_PROVIDER` 选择协议 |
| TTS | ChatTTS | 多说话人对话音频合成，LLM 口语化改写（默认关闭）|
| OCR | RapidOCR (ONNX) | CPU 推理，不占 GPU 显存 |
| 人脸检测 | ultralytics YOLO | yolov8n-face 轻量模型 |
| 文本纠错 | pycorrector (MacBERT) | 同音字/形近字检测 |
| 热词替换 | FlashText | 多模式高速匹配 |
| 纪要模板 | python-frontmatter | Markdown + YAML frontmatter 模板，热重载 |
| 音视频处理 | ffmpeg | 格式转换、音频增强、关键帧提取、MP3 合并 |
| 运行环境 | Python >= 3.12（pyenv 管理，固定 3.12.10） | CUDA GPU；开发机 Windows/Linux，生产 Rocky Linux |

---

## 二、目录结构

```
backend/src/copernicus/
  main.py                 # 应用入口 + Lifespan 生命周期 + 日志配置（版本 1.1.0，/docs 走 npmmirror CDN 的 Swagger UI）
  config.py               # pydantic-settings 配置（含 models_dir 派生路径等计算属性）
  dependencies.py         # FastAPI Depends 提供器（从 app.state 取服务实例）
  exceptions.py           # 自定义异常（CopernicusError 基类 + 子类）
  request_context.py      # 请求追踪：X-Request-ID 中间件 + 日志记录注入 request_id
  error_handlers.py       # 领域异常 → HTTP 状态码的统一映射（404 / 409 / 422 / 503 / 500）
  routers/                # FastAPI 路由层
    task.py               #   任务管理（列表/重命名/删除/上传/轮询/结果/重跑/媒体/转写校对）
    synthesis.py          #   TTS 音频合成与下载
    upload.py             #   分片上传（断点续传）
    evaluation.py         #   文本评估 + 模板管理
    compliance.py         #   合规审核（提交/复核/导出）
    transcription.py      #   /health 健康检查
  services/               # 业务服务层
    pipeline/             #   Pipeline 插件化编排
      base.py             #     PipelineContext + Stage Protocol
      orchestrator.py     #     顺序执行器
      __init__.py         #     PipelineService Facade
      stages/             #     9 个独立 Stage 实现
        video_preprocess.py
        keyframe_extract.py
        ocr_scan.py
        face_detect.py
        audio_preprocess.py
        asr_transcribe.py
        speaker_smooth.py
        text_correction.py
        transcript_build.py
    asr.py                #   双模式 ASR 服务
    tts.py                #   ChatTTS 多说话人合成
    corrector/            #   四阶段文本纠正（包）
      service.py          #     CorrectorService 编排
      preprocess.py       #     规则预处理（噪声词、重复词合并）
      prompts.py          #     LLM 润色 System Prompt
    text_corrector.py     #   pycorrector/MacBERT 封装
    hotword_replacer.py   #   FlashText 热词替换
    evaluator.py          #   Map-Reduce 内容评估（模板驱动）
    compliance.py         #   多源合规审核
    compliance_export.py  #   合规报告 Excel 导出
    transcript_edit.py    #   转写人工校对（文本修订、说话人改名/合并，纯函数）
    compliance_filters.py #   后处理过滤器链
    rule_registry.py      #   结构化规则注册表
    llm/                  #   LLM 客户端包：base（重试 + 并发）/ ollama / openai_compat / 工厂
    persistence.py        #   JSON 文件持久化 + 去重
    task_store.py         #   任务生命周期管理
    template_manager.py   #   纪要模板加载与热重载（Markdown + frontmatter）
    model_manager.py      #   GPU 模型生命周期管理（ASR↔TTS 互斥）
    audio.py              #   音频格式转换
    ocr.py                #   RapidOCR 封装
    face_detector.py      #   YOLO 人脸检测
    upload_session.py     #   分片上传会话管理
    lifecycle.py          #   磁盘生命周期：过期媒体 / 失败任务 / 中断上传 / 存储配额
    preflight.py          #   启动预检（模型文件、LLM 可达性、funasr 补丁）
  schemas/                # Pydantic 数据模型
    task.py               #   TaskStatus / TaskProgress / TaskResultsResponse
    transcription.py      #   TranscriptEntrySchema / TranscriptResponse + HealthResponse 系列
    evaluation.py         #   EvaluationResult（title + formatted_content）
    compliance.py         #   Violation / ComplianceReport / ComplianceRule
    visual.py             #   KeyFrame / OCRRecord / VisualEvent
    synthesis.py          #   SynthesisRequest / Response / StatusResponse
    upload.py             #   UploadQueryResponse / UploadChunkResponse
  utils/                  # 纯函数工具
    llm_parse.py          #   strip_think_tags / extract_json_object / extract_json_array
    text.py               #   chunk_text / merge_chunks / pre_merge_segments / smooth_speakers
    ffmpeg.py             #   ffmpeg 子进程封装
    request.py            #   parse_hotwords
    types.py              #   ProgressCallback / StageChangeCallback 类型别名
```

**开发启动**: `run_dev.py` 预设 CUDA/线程环境变量后以 uvicorn reload 模式启动（端口 8000）；开发日志按每 8 小时一个文件写入 `logs/YYYY-MM-DD_HH.log`（时段槽 00/08/16，追加写，启停时插入分隔标记），并通过 `COPERNICUS_LOG_FILE` 让 reload worker 复用同一文件。生产环境（systemd）日志走 stdout 由 journald 接管。

---

## 三、启动流程（Lifespan）

FastAPI 通过 `@asynccontextmanager` 管理应用生命周期，启动时按依赖顺序初始化所有服务：

```
0. 启动预检（preflight）
   └── run_preflight：检查模型文件是否就绪、LLM 服务可达性、funasr 补丁是否已应用

1. 环境变量修补
   └── LOKY_MAX_CPU_COUNT / OMP_NUM_THREADS（修复 joblib 物理核心检测）
   └── MODELSCOPE_CACHE 指向 models/funasr/ + PYTORCH_CUDA_ALLOC_CONF=expandable_segments

2. LLM 客户端（create_llm_client，按 LLM_PROVIDER 选择 Ollama 或 OpenAI 兼容实现）
   └── 全局 Semaphore(llm_max_concurrent) + httpx.AsyncClient

3. 基础服务
   ├── AudioService（ffmpeg 音频转换）
   ├── ASRService（FunASR 模型加载，GPU 显存）
   ├── TextCorrectorService（MacBERT 纠错模型）
   └── HotwordReplacerService（FlashText 热词表）

4. CorrectorService
   └── 组合: LLMClient + TextCorrectorService + HotwordReplacerService

5. PersistenceService
   └── upload_dir 目录初始化

6. 视觉服务（条件加载）
   ├── OCRService（ocr_enabled=true 时）
   └── FaceDetectorService（face_detect_enabled=true 时）

7. PipelineService
   └── 注册 9 个 Stage，注入所有依赖

8. 上层服务
   ├── TemplateManager（扫描 templates/ 目录，加载所有 .md 模板）
   ├── EvaluatorService（LLMClient + Settings + TemplateManager）
   └── ComplianceService（LLMClient + Settings）

9. ModelManager
   └── 注册 ASR / TTS 加载器（互斥锁模式）

10. TaskStore
    └── 注入 Pipeline + Persistence + Evaluator + Compliance + TemplateManager
    └── restore_from_disk() 恢复历史任务：有结果的为 COMPLETED，保留媒体但无结果的（失败或被重启打断）为 FAILED；同时修剪失效 hash 索引

11. LifecycleService
    └── asyncio 定时任务：启动时立即执行一次，之后每小时执行；策略见 6.9 末尾的"磁盘生命周期"
```

**关闭时**: 取消全部后台任务（标记为失败"任务已取消"）、取消 LifecycleService 定时任务，调用 `llm_client.close()` 释放 httpx 连接池。

**CORS**: 默认允许 `http://localhost:3000`。

**异常处理**: CopernicusError 统一转为 500 + JSON detail。

---

## 四、路由层

### 4.1 任务路由 (routers/task.py)

| 端点 | 方法 | 功能 |
|------|------|------|
| /api/v1/tasks/standard_minutes | POST | **主入口**：上传文件，ASR + 纠错 + 摘要全流程 |
| /api/v1/tasks/transcript | POST | 轻量入口：仅 ASR + 纠错，不含摘要 |
| /api/v1/tasks | GET | 历史任务列表（按创建时间倒序，含运行中与失败的任务，`limit` 上限 500）|
| /api/v1/tasks/lookup | GET | 按文件 SHA-256 查询已有任务（上传前预检）|
| /api/v1/tasks/{task_id} | GET | 查询任务状态和进度（前端轮询）|
| /api/v1/tasks/{task_id} | PATCH | 重命名任务（显示名称）|
| /api/v1/tasks/{task_id}/results | GET | 获取完整持久化结果 |
| /api/v1/tasks/{task_id}/media | GET | 获取原始媒体文件（视频优先，回退音频）|
| /api/v1/tasks/{task_id}/frames/{filename} | GET | 获取关键帧 JPEG 图片 |
| /api/v1/tasks/{task_id}/rerun-transcript | POST | 基于已有音频重新转写（运行中返回 409，队列已满返回 429）|
| /api/v1/tasks/{task_id}/cancel | POST | 取消排队或 LLM 阶段的任务；ASR / 视觉扫描阶段返回 409 |
| /api/v1/tasks/{task_id}/transcript | PATCH | 人工修订句段的修正文（按下标批量）|
| /api/v1/tasks/{task_id}/speakers | PATCH | 重命名或合并说话人 |
| /api/v1/tasks/{task_id} | DELETE | 默认仅作废缓存；`purge=true` 彻底删除任务及磁盘文件 |

**standard_minutes 参数**: `file` + `hotwords` + `visual_scan` + `generate_summary` + `template_id`（默认 universal）。

**results 端点**: 合并 transcript.json / evaluation.json / compliance.json + 媒体元数据（has_audio / has_video / **has_synthesis** / keyframe_count / ocr_text_count / visual_event_count）。`has_synthesis` 由服务端检测 `synthesis.mp3` 是否存在决定。

### 4.2 评估路由 (routers/evaluation.py)

| 端点 | 方法 | 功能 |
|------|------|------|
| /api/v1/templates | GET | 获取所有可用纪要模板列表 |
| /api/v1/templates/reload | POST | 热重载模板目录（无需重启服务）|
| /api/v1/evaluate/text/async | POST | 提交纯文本评估任务（含 template_id）|
| /api/v1/evaluate/transcript/async | POST | 接收第三方转写并评估 |

`evaluate/text/async` 接收 `text + parent_task_id + template_id`，结果持久化到 parent 任务目录。

### 4.3 合规路由 (routers/compliance.py)

| 端点 | 方法 | 功能 |
|------|------|------|
| /api/v1/tasks/compliance_audit | POST | 提交合规审核任务 |
| /api/v1/tasks/{task_id}/compliance/violations | PATCH | 批量更新违规审核状态 |
| /api/v1/tasks/{task_id}/compliance/export | GET | 导出 Excel 报告（概览 + 违规明细）|

audit 端点接收 rules_file（CSV/XLSX）+ transcript（JSON 字符串）+ parent_task_id。violations PATCH 端点接收 `[{violation_id, status}]` 数组（`violation_id` 为报告内稳定唯一标识；旧的 `index` 字段仍兼容但已废弃），每项可带 `note` 复核备注；确认/驳回会记录复核时间，改回待审则清空留痕。合规评分随复核重算（已驳回的条目不再扣分），响应返回实际更新数、未匹配的目标与最新评分。导出的 Excel 对来自转写与模型的文本做了公式注入防护（以 = 开头的内容按文本存储）。

### 4.4 音频重塑路由 (routers/synthesis.py)

| 端点 | 方法 | 功能 |
|------|------|------|
| /api/v1/tasks/{task_id}/synthesize | POST | 将转写结果合成为多说话人对话音频 |
| /api/v1/tasks/{task_id}/synthesis/status | GET | 查询合成任务状态（running / completed / failed）|
| /api/v1/tasks/{task_id}/synthesis | GET | 下载已合成的 MP3 文件 |

synthesize 端点接收可选 `voice_map`（JSON，说话人→音色种子映射），任务完成后将 `synthesis.mp3` 写入任务目录。

### 4.5 分片上传路由 (routers/upload.py)

| 端点 | 方法 | 功能 |
|------|------|------|
| /api/v1/uploads/{hash} | GET | 查询或创建上传会话 |
| /api/v1/uploads/{hash} | PATCH | 上传数据块（Content-Range 协议）|

**断点续传**: GET 接口返回已接收字节数，PATCH 携带 `Content-Range: bytes start-end/total`，服务端顺序写入临时文件。所有分块接收完毕后自动触发 `submit_standard_minutes` 流水线。

### 4.6 系统路由 (routers/transcription.py)

| 端点 | 方法 | 功能 |
|------|------|------|
| /api/v1/health | GET | 服务健康检查（就绪探针，unhealthy 时返回 503）|
| /api/v1/health/live | GET | 存活探针，仅表示进程可响应，不检查任何依赖 |

**health 响应结构**: 顶层 `status`（healthy / degraded / unhealthy）+ 三个组件对象 `asr` / `llm` / `tts`（各含 status: ok / degraded / down 与 detail）+ `tasks` 任务统计（active / completed / failed / synthesis_running）+ `vram` 水位（loaded_models / estimated_used_gb / budget_gb）。早期的同步转录调试端点已删除。

---

## 五、Pipeline 插件化架构

### 5.1 核心抽象

**Stage Protocol**: 每个处理阶段需实现三个要素：

- `name: str` -- 阶段名称标识
- `execute(ctx, on_progress) -> PipelineContext` -- 执行逻辑
- `should_run(ctx) -> bool` -- 是否跳过

**PipelineContext（数据总线）**: 所有 Stage 共享的可变数据对象，跨阶段传递数据：

```
PipelineContext
  输入字段:
    task_id / audio_bytes / filename / hotwords / sentence_timestamp

  音频处理:
    wav_path            -- 转换后的 WAV 文件路径

  ASR 输出:
    asr_result          -- FunASR 原始结果
    segments            -- 分段列表（text / start_ms / end_ms / speaker / confidence）

  纠正输出:
    correction_map      -- {segment_id: corrected_text}

  转写输出:
    transcript_entries   -- 最终 TranscriptEntry 列表

  视觉字段:
    video_path          -- 原始视频文件路径
    keyframes           -- 关键帧列表
    ocr_results         -- OCR 扫描结果
    visual_events       -- 视觉事件（人脸检测）
    media_type          -- "audio" | "video"

  计时:
    processing_times    -- {stage_name: elapsed_ms}
```

### 5.2 Orchestrator 编排器

PipelineOrchestrator 顺序遍历已注册的 Stage 列表：

```
for each stage in stages:
    if stage.should_run(ctx) == False:
        skip (log debug)
    else:
        build per-stage progress callback
        start = perf_counter()
        ctx = await stage.execute(ctx, on_progress)
        ctx.processing_times[stage.name] = elapsed_ms
        log completion
return ctx
```

**进度回调签名**: `StageProgressCallback(stage_name, stage_idx, total_stages, current, total)`，由 Orchestrator 将 per-stage 回调（current, total）包装为全局回调。

### 5.3 PipelineService Facade

PipelineService 是对外暴露的唯一接口，构造时注册 9 个 Stage：

```
1. VideoPreprocessStage     -- 视频提取音频（条件注册：settings + persistence）
2. KeyframeExtractStage     -- 关键帧提取（条件注册：settings + persistence）；场景切换策略使用 ffmpeg showinfo 报告的真实时间戳，等间隔策略按间隔推算，保证与转写、OCR 的时间对齐
3. OCRScanStage             -- OCR 扫描（条件注册：ocr_service + persistence）
4. FaceDetectStage          -- 人脸检测（条件注册：face_detector + persistence + settings）
5. AudioPreprocessStage     -- 音频格式转换
6. ASRTranscribeStage       -- 语音识别
7. SpeakerSmoothStage       -- 说话人标签平滑
8. TextCorrectionStage      -- 四阶段文本纠正
9. TranscriptBuildStage     -- 转写结果构建
```

**执行顺序**: 视觉阶段（关键帧/OCR/人脸检测）排在音频预处理与 ASR 之前，仅在 `visual_scan=true` 且为视频任务时执行。

**条件注册**: 视觉相关 Stage（1/2/3/4）仅在相关服务和 persistence 都存在时才注册到 Orchestrator，缺少依赖时整个 Stage 不注册。

**热词合并**: process_transcript 调用时，将全局热词（HotwordReplacerService 提取的 ASR 热词）与请求级热词合并。

**进度透传**: 仅 text_correction Stage 的进度向外报告，其他 Stage 的进度被过滤。

---

## 六、服务层详解

### 6.1 ASR 双模式服务 (asr.py)

| 模式 | 适用场景 | 实现方式 |
|------|---------|---------|
| Paraformer | 多人对话，需说话人分离 | VAD + ASR + PUNC + SPK 四合一推理 |
| SenseVoice | 嘈杂环境，需抗噪增强 | ASR 独立推理 + Campplus 滑动窗口声纹聚类 |

**GPU 保护**: ASRTranscribeStage 持有 asyncio.Lock，保证同一时刻仅一个 ASR 推理任务占用 GPU。

**SenseVoice 后处理链**:
1. 清洗特殊标记和 emoji
2. 超长段落按标点+时长智能拆分（max_segment_ms）
3. 纯噪声段落过滤（语气词、英文幻觉短语）
4. Campplus 滑动窗口声纹提取 + 余弦距离聚类说话人分离
5. 单段多说话人自动拆分

**Paraformer 特性**: 集成 spk_model 直接输出说话人标签，batch_size_s 上限 60s 防 OOM，sentence_timestamp 支持。

### 6.2 四阶段文本纠正 (corrector.py)

```
原始 ASR 文本
    ↓
阶段 1: 规则预处理 (preprocess_text)
  ├── 纯噪声短语检测（英文 ASR 幻觉：the, um, uh 等）
  ├── 英文噪声前缀清理
  ├── 重复词合并（12 种模式："那个那个" → "那个"）
  ├── 中文数字年份转阿拉伯数字（"二零二五年" → "2025年"）
  ├── 纯标点/空文本检测
  └── 纯语气词检测（嗯/啊/哦 等 14 个）
    ↓ 过滤后有效条目
阶段 2: 热词强制替换 (HotwordReplacerService)
  └── FlashText 多模式匹配，一次遍历完成所有替换
    ↓
阶段 3: pycorrector 轻量纠错 (TextCorrectorService)
  └── MacBERT 模型检测同音字/形近字（可配置开关）
    ↓
阶段 4: LLM 润色 (LLMClient)
  ├── JSON-to-JSON 格式：{"entries": [{id, text}]} → {"entries": [{id, text}]}
  ├── System Prompt: 字幕校对专家，严禁合并/拆分/改写
  ├── 批次分组：同时满足 max_entries(15) 和 max_chars(800) 限制
  ├── 并发控制：Semaphore(correction_max_concurrency)
  ├── think=False 禁用推理模式，减少 token 消耗
  ├── num_predict 动态计算：batch_chars * 2 + 1024
  └── 降级策略：JSON 解析失败 → 正则提取 id/text 对 → 原文 fallback
```

**噪声条目处理**: 阶段 1 标记为过滤的条目在最终结果中设为空字符串，TranscriptBuildStage 会移除这些空条目。

### 6.3 模板驱动 Map-Reduce 评估 (evaluator.py + template_manager.py)

**TemplateManager**: 扫描 `templates/` 目录下所有 `.md` 文件（YAML frontmatter 定义 id / name / description，正文即 prompt）。当前内置 5 个模板：universal（通用，默认）、daily_evening（夕会）、weekly（周例会）、official（公文）、brief_summary（约 100 字简报）。支持 `reload()` 热重载，无需重启服务。

**评估模式**:

- **短文本路径**（文本长度 <= chunk_size）: 单次 LLM 调用，注入模板 prompt，直接生成纪要 Markdown。
- **长文本路径**（文本长度 > chunk_size）: Map-Reduce 两阶段处理。

```
Map 阶段:
  ├── chunk_text 按句子边界分段
  ├── asyncio.gather 并发处理所有分段
  ├── 每段提取 2-5 条核心观点 + 关键数据 + 主题概括
  ├── think=False + num_predict=1024（快速输出）
  └── 失败 fallback：截取原文前 500 字

Reduce 阶段:
  ├── 合并所有分段要点（"【片段 1/N】\n..."格式）
  ├── 注入选定模板 prompt
  ├── 单次 LLM 调用生成最终纪要 Markdown
  └── JSON 解析重试（附加"请严格输出JSON"提示）
```

**评估输出结构**: `title`（纪要标题）+ `formatted_content`（Markdown 格式纪要正文）。

### 6.4 多源合规审核 (compliance.py)

完整审核流程：

```
1. 规则解析
   ├── parse_rules(file_bytes, filename) 支持 CSV / XLSX
   ├── CSV 多编码 fallback（utf-8-sig / gbk / gb18030）
   ├── A 列为规则，B-G 列为历史违规案例（few-shot）
   └── 编号与内容自动分离（"4全程双录：..." → id=4, content="全程双录：..."）

2. 规则结构化（RuleRegistry）
   ├── 按内容关键词匹配 13 条内置规则（非按 ID 盲匹配）
   ├── 每条规则标注 category / check_mode / evidence_sources / keywords
   ├── 未匹配规则 fallback 为默认 semantic 模式
   └── 按 evidence_sources 分组：transcript / ocr / mixed

3. Map 阶段（并发审核）
   ├── entries 按字符数分 chunk（保证每条 entry 完整）
   ├── 规则分组 x chunk 组合并发
   ├── OCR 数据按时间对齐注入（margin_ms 边界匹配）
   ├── 四步 CoT 推理 prompt（理解边界 → 提取证据 → 判断违规 → 置信度）
   ├── JSON 数组输出 + 反向约束（明确什么不是违规）
   └── 时间戳精确映射（LLM 输出 timestamp → 原始 entry 的 timestamp_ms）

4. 后处理过滤器链
   ├── ConfidenceFilter: 丢弃 confidence < threshold 的违规
   ├── ExactMatchValidator: exact 模式规则二次验证
   │     ├── 正则匹配 + 拼音回退匹配（ASR 同音字场景）
   │     ├── LLM 报告但正则未命中 → 丢弃（误报）
   │     └── 正则命中但 LLM 遗漏 → 补充（漏报）
   ├── DeduplicationFilter: 同 rule_id 且时间差 < window_ms 的合并
   └── EvidenceEnricher: 为 transcript 来源违规补充最近 OCR 截图证据

5. Reduce 阶段（摘要生成）
   ├── LLM 生成 200 字以内合规总结
   ├── 失败 fallback：统计模板（"发现 N 条违规（高 X、中 Y、低 Z）"）
   └── 合规评分计算：基础 100 分，high -15 / medium -8 / low -3
```

### 6.5 规则注册表 (rule_registry.py)

内置 13 条保险产说会合规规则的结构化元数据：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 规则编号 |
| title | str | 规则标题 |
| content | str | 规则内容（来自 CSV） |
| category | Literal | forbidden_phrase / behavioral / document / visual_check |
| check_mode | Literal | exact（精确匹配）/ semantic（语义审核）/ visual（视觉审核） |
| evidence_sources | list[str] | 需要的证据来源：transcript / ocr |
| keywords | list[str] | exact 模式的关键词列表 |
| description | str | 审核说明（注入 prompt 的核心依据） |
| severity_default | Literal | 默认严重程度 |

**匹配策略**: 按 CSV 规则内容中的关键词匹配内置规则（非按 ID），每条内置规则定义了匹配 token 列表，计算命中数取最高分。

**exact 预编译**: 为 exact 模式规则预编译正则表达式和拼音索引，供过滤器链高速匹配。

**分组逻辑**: group_by_source 将规则分为 transcript-only / ocr-only / mixed 三组，OCR-only 组在无 OCR 数据时自动跳过。

### 6.6 后处理过滤器链 (compliance_filters.py)

按顺序执行四个过滤器：

```
ConfidenceFilter
  → 丢弃 confidence < 0.7 的违规

ExactMatchValidator
  → Python 正则二次验证 exact 模式规则
  → 拼音回退匹配（pypinyin 滑动窗口，应对 ASR 同音字）
  → 补充全文扫描漏报

DeduplicationFilter
  → 同 rule_id 且时间差 < 30s 的合并，保留最高 confidence

EvidenceEnricher
  → 为 transcript 来源违规关联最近 OCR 截图作为辅助证据
```

### 6.7 ChatTTS 多说话人合成 (tts.py)

**LLM 口语化改写**: 合成前调用 LLM 将书面化转写文本改写为自然口语风格，按说话人分段处理。

**多说话人音色**: 按说话人哈希分配固定种子（`_voice_to_seed`），同一说话人每次合成音色一致。支持自定义 `voice_map` 覆盖默认分配。

**合成流程**:

```
转写条目（按说话人合并）
    ↓
LLM 口语化改写（_rewrite_chunks，按说话人并发）
    ↓
_sanitize_for_chattts（清洗特殊字符）
    ↓
_split_by_uv_break / _slice_sentences（防幻读拆分，max=40字/句）
    ↓
synthesize_dialogue_batched（批次合成，每批 1000 字清空 VRAM 缓存）
    ↓
_apply_fade（淡入淡出处理）
    ↓
concat_parts_to_mp3（ffmpeg 合并为 synthesis.mp3）
```

**ModelManager 互斥**: synthesize 路由在合成前通过 `model_manager.acquire("tts")` 卸载 ASR 模型，合成完成后可重新加载 ASR。

### 6.8 LLM 客户端 (services/llm/)

客户端包由三部分组成，上层服务只依赖抽象类型 LLMClient：

| 模块 | 职责 |
|------|------|
| base | 抽象基类：全局并发信号量、指数退避重试、超时覆盖，协议细节交由子类 |
| ollama | Ollama 原生 /api/chat 协议（支持 num_ctx、think、keep_alive、format=json），另提供 TTS 改写专用的独立实例 |
| openai_compat | OpenAI 兼容 /chat/completions 协议（SSE 流式，Bearer 鉴权，response_format 输出 JSON，用量取自 usage）|

**协议选择**: 由 `LLM_PROVIDER`（ollama / openai）决定，`create_llm_client` 工厂创建单例。openai 协议请求地址为 `{LLM_BASE_URL}/chat/completions`，OpenAI 等需要 /v1 的服务须在地址中带上；DeepSeek 直接使用其根地址。Ollama 专有参数（num_ctx、think、keep_alive）在 openai 协议下被忽略。

**流式响应**: 所有请求使用流式，逐 token 接收。非流式模式下 httpx 必须等待整个推理完成，复杂文本可能超过 120 秒导致 ReadTimeout；流式模式下只要 token 间隔 < read_timeout 就不会超时。

**并发控制**: asyncio.Semaphore(llm_max_concurrent) 全局限制，chat 方法在获取信号量后才发起请求。

**重试机制**: 仅对可恢复错误重试——ReadTimeout、ConnectError、流式响应被对端中断、HTTP 5xx 与 429；401/404/422 等 4xx（鉴权或参数错误）重试无意义，直接抛出。延迟按指数退避（2^attempt * retry_delay）。

**chat 方法参数**:

| 参数 | 说明 |
|------|------|
| messages | 对话消息列表 |
| temperature | 温度（默认 0.1） |
| json_format | 强制 JSON 输出（Ollama format="json" / OpenAI response_format=json_object）|
| num_ctx | 上下文窗口大小（仅 Ollama）|
| think | None=默认 / False=禁用推理 / True=强制推理（仅 Ollama）|
| num_predict | 最大输出 token 数（OpenAI 协议映射为 max_tokens）|
| timeout | 覆盖默认 read timeout |

**健康检查**: is_reachable() 在 Ollama 下调用 /api/tags，在 openai 协议下调用 /models，均为 5 秒超时。

### 6.9 持久化服务 (persistence.py)

**原子写入**: 所有 JSON 写入通过 tempfile + rename，避免中断导致数据损坏。

**目录布局**:

```
uploads/
  hash_index.json               -- SHA-256 → task_id 映射
  {task_id}/
    meta.json                   -- 任务元数据（filename/hash/media_type/created_at）
    transcript.json             -- 转写结果
    evaluation.json             -- 评估结果（title + formatted_content）
    compliance.json             -- 合规审核结果
    synthesis.mp3               -- TTS 合成对话音频（可选）
    synthesis_result.json       -- 合成耗时与音频时长元数据（可选）
    keyframes.json              -- 关键帧元数据
    ocr_results.json            -- OCR 扫描结果
    visual_events.json          -- 视觉事件
    audio.{ext}                 -- 原始或提取的音频
    video.{ext}                 -- 原始视频（视频任务）
    frames/                     -- 关键帧图片
      0001.jpg / 0002.jpg / ...
```

**核心方法**:

| 方法 | 说明 |
|------|------|
| save_json / load_json | Pydantic model 序列化/反序列化 |
| has_file / delete_file | 文件存在检查/删除 |
| save_meta / load_meta | 任务元数据读写 |
| save_audio / find_audio | 音频保存/查找（兼容 legacy 路径） |
| save_video / find_video | 视频保存/查找 |
| frames_dir | 获取关键帧目录路径 |
| task_dir | 获取任务目录路径 |
| load_hash_index / save_hash_index | SHA-256 去重索引 |
| scan_completed_tasks | 扫描磁盘恢复内存任务 |

**磁盘生命周期 (lifecycle.py)**: 后台每小时（启动时立即一次）依次执行四项策略：

| 策略 | 说明 |
|------|------|
| 过期媒体 | 已完成任务超过 media_retention_hours 后删除原始音视频与合成音频，保留转写/纪要/合规 JSON 与关键帧证据 |
| 失败任务 | 没有转写结果的任务（失败或被重启打断）超期后整目录删除；等待时间至少 2 小时，避免误删仍在处理的任务 |
| 中断上传 | 超期未完成的分片上传会话整目录删除 |
| 存储配额 | max_storage_gb > 0 且占用超限时，按时间从旧到新删除原始媒体直到回落 |

时间以 created_at 与重新转写时写入的 processed_at 中较晚者为准，因此被重跑的旧任务在处理期间不会被当作过期任务清理。

### 6.10 任务管理 (task_store.py)

**TaskInfo 数据结构**: 轻量级 `__slots__` 对象，字段包括 task_id / status / current_chunk / total_chunks / result / error / eval_only / audio_path / parent_task_id。

**任务提交方法**:

| 方法 | 说明 |
|------|------|
| submit_standard_minutes | ASR + 纠正 + 摘要全流程，asyncio.create_task 异步执行 |
| submit_transcript | ASR + 纠正，不含摘要（轻量版） |
| submit_text_evaluation | 纯文本评估（无 ASR），关联 parent_task_id |
| submit_compliance_audit | 合规审核，自动加载 OCR/visual_events 数据 |

**任务执行包装**: _run_with_timeout 使用 asyncio.wait_for 包装，超时自动标记 FAILED。_task_lifecycle 上下文管理器统一处理 try/except + 状态设置 + 日志。

**进度计算逻辑**:

| 状态 | 百分比计算 |
|------|-----------|
| PENDING | 0% |
| EXTRACTING_FRAMES | 5% |
| SCANNING_VISUAL | 5% + (current/total) * 15% |
| PROCESSING_ASR | 20% |
| CORRECTING | 20% + (current/total) * 70% |
| EVALUATING（独立任务）| (current/total) * 100% |
| EVALUATING（附属任务）| 90% + (current/total) * 10% |
| AUDITING | (current/total) * 100% |
| COMPLETED | 100% |

**任务管理**:

| 方法 | 说明 |
|------|------|
| list_tasks | 以磁盘扫描为准合并内存状态，返回按创建时间倒序的摘要；名称优先级：用户重命名 > 纪要标题 > 原始文件名 |
| rename_task | 写入 meta.json 的 display_name |
| purge_task | 彻底删除内存状态、哈希索引与磁盘目录；任务或合成仍在运行时抛出 TaskBusyError（409）|
| edit_transcript / rename_speakers | 校对结果回写 transcript.json 并同步内存中的任务结果，仅已完成任务允许；说话人多对一映射即合并 |

**内存管理**: LRU 淘汰机制，任务数超过 task_max_in_memory 时移除最早的已完成/失败任务。

**重跑机制**: rerun_transcript 重置任务状态并删除下游 evaluation/compliance 持久化文件。重跑读取磁盘上的已存媒体，视频优先、回退音频（视频任务也可重跑）。

### 6.11 OCR 服务 (ocr.py)

RapidOCR 的懒加载封装，首次 scan_frame 调用时才初始化引擎（ONNX CPU 推理）。

**scan_frame 方法**: 接收图片路径和时间戳，返回 OCRRecord 列表。内置置信度过滤（ocr_confidence_threshold）和最小文本长度过滤（ocr_min_text_length）。

### 6.12 人脸检测服务 (face_detector.py)

YOLO face 模型的懒加载封装，CPU 推理。

**detect_frame 方法**: 检测单帧人脸，返回 bbox + confidence 列表。

**analyze_face_timeline 方法**: 将逐帧检测结果聚合为时间线事件。使用状态机合并相邻相同状态的帧为连续 VisualEvent（face_detected / face_missing），短暂 face_missing（< face_missing_threshold_ms）自动过滤。

### 6.13 GPU 模型管理器 (model_manager.py)

单 GPU 多模型互斥加载，保证 ASR 与 TTS 不同时占用显存：

```
register_loader(model_type, loader, unloader, vram_estimate_gb)
  -- 插件式注册（ASR / TTS 各自注册加载/卸载回调）

acquire(model_type)  -- async context manager
  1. 若目标已加载 → 直接使用
  2. 若其他模型已加载 → 先 unload（torch.cuda.empty_cache + gc.collect）
  3. 再 load 目标模型
  4. 退出 context 后不自动卸载（保持常驻，下次 acquire 竞争时才卸载）

unload(model_type) / unload_all()
  -- 显式卸载 + 显存清理
```

**当前注册**: ASR（asr.py 中的 FunASR 加载器）和 TTS（tts.py 中的 ChatTTS 加载器）。OCR 和 YOLO 通过懒加载直接 CPU 推理，不经过 ModelManager。

---

## 七、工具函数层

### 7.1 llm_parse.py

| 函数 | 说明 |
|------|------|
| strip_think_tags | 移除 LLM 输出中的 `<think>...</think>` 标签（含未闭合标签） |
| extract_json_object | 从 LLM 输出中提取 JSON 对象（去 Markdown fence + 定位 `{}`） |
| extract_json_array | 从 LLM 输出中提取 JSON 数组（优先定位 `[]`，fallback 定位 `{}`） |

### 7.2 text.py

| 函数 | 说明 |
|------|------|
| chunk_text | 按句子边界分段（句号/问号/感叹号），支持 overlap |
| merge_chunks | 重组纠正后的分段，跳过 overlap 区域去重 |
| split_sentences | 按中文标点分句 |
| format_timestamp | 毫秒转 MM:SS 格式 |
| pre_merge_segments | ASR 段落预合并（同说话人 + gap < gap_ms），保留 sub_sentences |
| smooth_speakers | 说话人标签平滑（短暂切换 < max_duration_ms 归入前后说话人） |
| split_corrected_by_sub_sentences | LLM 纠正文本按比例分配回 sub_sentence 时间区间 |
| split_original_by_sub_sentences | 原始文本按 sub_sentence 前缀匹配拆分 |
| group_segments | ASR 段落按字符数分组 |
| merge_transcript_entries | 连续同说话人条目合并（gap < threshold） |

### 7.3 request.py

parse_hotwords: 解析请求中的 hotwords JSON 字符串为 list[str]，校验类型和格式。

### 7.4 types.py

ProgressCallback: `Callable[[int, int], None]` 类型别名，(current, total) 通用进度回调。

---

## 八、配置体系

所有配置通过 pydantic-settings 从 .env 文件加载，类型安全：

### 8.1 ASR 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| asr_mode | "paraformer" | ASR 模式切换 |
| asr_device | "auto" | 自动检测 CUDA |
| asr_batch_size | 3000 | 16GB 显存推荐值 |
| asr_dtype | "float16" | FP16 推理 |
| spk_sliding_window_ms | 1500 | 声纹提取窗口 |
| spk_sliding_step_ms | 750 | 窗口滑动步长 |
| spk_distance_threshold | 0.5 | 余弦距离阈值 |
| filter_noise_segments | true | 过滤纯语气词段落 |
| sensevoice_max_segment_ms | 15000 | 单段最大时长 |

### 8.2 LLM 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| llm_provider | "ollama" | 协议：ollama（原生 /api/chat）或 openai（OpenAI 兼容 /chat/completions）|
| llm_api_key | "" | API Key，openai 协议必填，以 Bearer 头发送 |
| llm_base_url | "http://localhost:11434" | LLM 服务地址 |
| llm_model_name | "qwen3:latest" | 模型名称 |
| llm_temperature | 0.1 | 低温度保证一致性 |
| llm_timeout | 120.0 | 单次请求超时（秒） |
| llm_max_retries | 2 | 重试次数 |
| llm_retry_delay | 2.0 | 首次重试延迟 |
| llm_max_concurrent | 3 | 全局并发上限 |
| ollama_num_ctx | 32768 | 通用上下文窗口 |
| ollama_num_ctx_correction | 4096 | 纠正专用上下文窗口 |

### 8.3 纠正配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| correction_chunk_size | 800 | 分段大小（字符） |
| correction_overlap | 50 | 重叠区域（字符） |
| correction_max_concurrency | 3 | LLM 纠正并发数 |
| confidence_threshold | 0.95 | 跳过纠正的置信度门槛 |
| pre_merge_gap_ms | 1000 | 段落预合并时间间隔 |
| pycorrector_enabled | true | MacBERT 纠错开关 |
| hotword_replacer_enabled | true | 热词替换开关 |

### 8.4 评估配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| evaluation_max_text_chars | 50000 | 文本总上限 |
| evaluation_chunk_size | 6000 | Map 分段大小 |
| evaluation_num_ctx | 8192 | 评估专用 num_ctx |

### 8.5 合规配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| compliance_max_text_chars | 50000 | 文本总上限 |
| compliance_chunk_size | 4000 | Map 分段大小 |
| compliance_num_ctx | 8192 | 审核专用 num_ctx |
| compliance_confidence_threshold | 0.7 | 置信度过滤门槛 |
| compliance_dedup_window_ms | 30000 | 去重时间窗口 |
| compliance_group_by_source | true | 按来源分组审核 |
| compliance_ocr_margin_ms | 5000 | OCR 时间对齐边界 |

### 8.6 视觉处理配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| video_extensions | ".mp4,.avi,.mov,.mkv,.flv,.wmv" | 视频扩展名 |
| keyframe_strategy | "interval" | 提帧策略（interval / scene） |
| keyframe_interval_s | 2.0 | 固定间隔（秒） |
| keyframe_scene_threshold | 0.3 | 场景变化检测阈值 |
| keyframe_max_count | 500 | 最大帧数 |
| ocr_enabled | true | OCR 总开关 |
| ocr_confidence_threshold | 0.6 | OCR 置信度门槛 |
| ocr_min_text_length | 2 | OCR 最小文本长度 |
| face_detect_enabled | true | 人脸检测总开关 |
| face_detect_confidence | 0.5 | 人脸检测置信度门槛 |
| face_missing_threshold_ms | 10000 | 短暂缺失过滤阈值 |

YOLO 模型路径为计算属性，固定为 `models_dir/yolo/yolov8n-face.pt`，无需单独配置。

### 8.7 任务配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| task_timeout_seconds | 3600 | 单任务超时 |
| task_max_active | 5 | 排队+运行中的音视频任务上限，超出返回 429（0 = 不限制）|
| task_max_in_memory | 500 | 内存任务数上限 |
| upload_dir | "./uploads" | 持久化根目录 |
| max_upload_size_mb | 500 | 上传文件大小上限 |
| vram_budget_gb | 12.0 | ModelManager 热插拔的 VRAM 预算 |
| media_retention_hours | 24 | 原始媒体文件保留时长（超时由 LifecycleService 清理）|
| max_storage_gb | 0 | 上传目录磁盘配额（GB），超出时从最旧的任务起删除原始媒体；0 = 不限制 |
| models_dir | "./models" | 统一模型根目录（funasr / chattts / yolo）|
| templates_dir | "./templates" | 纪要模板目录 |

### 8.8 TTS 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| tts_max_sentence_chars | 40 | 单句最大字符数（防幻读）|
| tts_synthesis_batch_chars | 1000 | 每批合成字符数（VRAM 缓存管理）|
| tts_vram_estimate_gb | 4.0 | TTS 显存估算（供 ModelManager）|
| tts_rewrite_enabled | false | 合成前 LLM 口语化改写开关 |
| tts_rewrite_base_url | "http://localhost:11434" | 改写专用 LLM（固定本地 Ollama，独立于主 LLM）|

ChatTTS 模型路径为计算属性，固定为 `models_dir/chattts/`，无需单独配置。

---

## 九、并发模型

```
FastAPI 事件循环（单进程 asyncio）
  │
  ├── 路由层：async 处理 HTTP 请求
  │
  ├── TaskStore.submit_*：asyncio.create_task 启动后台任务
  │     └── _run_with_timeout：asyncio.wait_for 超时保护
  │
  ├── ModelManager：互斥锁（asyncio.Lock）
  │     ├── ASR 推理：acquire("asr")，同一时刻仅一个任务
  │     └── TTS 合成：acquire("tts")，卸载 ASR 后加载
  │
  ├── LLM 调用：asyncio.Semaphore(3)
  │     ├── CorrectorService: Semaphore(correction_max_concurrency) 批次并发
  │     ├── EvaluatorService: asyncio.gather Map 分段并发
  │     └── ComplianceService: asyncio.gather chunk x group 并发
  │
  ├── OCR / YOLO：asyncio.to_thread 线程池
  │     └── CPU 推理不阻塞事件循环
  │
  ├── 分片上传：UploadSessionManager 内存会话
  │     └── 分块追加写磁盘，最终组装触发任务提交
  │
  └── 进度上报：各 _run_* 方法中的回调直接修改 TaskInfo 字段
        └── 前端 GET /tasks/{id} 读取最新值（无锁，单线程安全）
```

---

## 十、容错机制

| 层级 | 机制 | 说明 |
|------|------|------|
| LLM 请求 | 流式响应 | 避免长推理 ReadTimeout |
| LLM 请求 | 指数退避重试 | 2^attempt * delay，最多 retry 次 |
| LLM 输出 | JSON 解析重试 | 附加"请严格输出JSON"提示 |
| LLM 输出 | 正则 fallback | JSON 解析全失败时正则提取 id/text 对 |
| LLM 输出 | think 标签清理 | strip_think_tags 处理未关闭标签 |
| 评估 Map | chunk fallback | Map 单段失败时截取原文前 500 字替代 |
| 合规 Map | chunk 容错 | 单 chunk 审核失败被跳过并计入 failed_chunks，报告显式标记；全部 chunk 失败则任务失败，不产出"无违规"的假报告 |
| 合规 / 纪要 | 完整性标记 | 超过文本上限被截断时，报告 truncated=true 并给出已检查/总段落数；纪要 Map 阶段失败的分块计入 degraded_chunks |
| 合规摘要 | 模板 fallback | LLM 生成摘要失败时用统计模板替代 |
| 合规过滤 | exact 二次验证 | Python 正则 + 拼音匹配双重验证 |
| 任务执行 | 超时保护 | asyncio.wait_for(task_timeout_seconds) |
| 任务执行 | 生命周期包装 | _task_lifecycle 统一异常捕获 + 状态标记 |
| 文件持久化 | 原子写入 | tempfile + rename 防数据损坏 |
| 任务状态 | 失败原因落盘 | 任务失败时写入 failure.json（仅对有 meta.json 的任务），重启后恢复原始失败原因；无记录则提示"服务重启导致任务中断" |
| 任务状态 | 惰性恢复 | 内存淘汰后的任务在被查询时从磁盘重建，被用户作废（DELETE）的任务不再恢复 |
| 任务状态 | 重跑保护 | 运行中的任务不允许重新转写（409） |
| 任务调度 | 准入控制 | 排队+运行中的音视频任务达到 task_max_active 时返回 429；分片上传只拒绝新会话，已有会话仍可续传 |
| 任务调度 | 取消 | 保存后台任务句柄；仅排队与 LLM 阶段可取消（ASR 与视觉扫描在线程中无法中断，取消会让线程继续占用 GPU 并放行下一个任务）；关停时统一取消 |
| 可观测性 | 请求追踪 | 每个请求分配 X-Request-ID（可沿用调用方传入的合法值），写入响应头、错误响应体与所有日志行；请求内启动的后台任务继承该 id |
| 错误响应 | 统一结构 | 领域异常返回 {detail, code, request_id}；未预期异常只记录日志，返回通用文案与 request_id，不暴露异常内容 |
| 上传 | 线程卸载与串行 | 分块追加、组装、SHA-256 与落盘放入线程，不阻塞事件循环；同一文件的分块经每会话锁串行处理；超出声明大小的分块被拒绝 |
| 哈希索引 | stale 清理 | restore_from_disk() 启动时确定性清理并持久化；lookup 时发现 stale 条目惰性移除内存状态 |
| 分片上传 | 断点续传 | GET 返回已接收字节，客户端续传剩余分块 |

---

## 十一、显存优化策略

**硬件约束**: RTX 5080 Laptop 16GB VRAM，ASR 约占 4GB，TTS 约占 4GB，不可共存。

| 策略 | 实现 | 效果 |
|------|------|------|
| FP16 推理 | asr_dtype="float16" | 显存减半 |
| 动态 num_ctx | 纠正 4096 / 评估 8192 / 通用 32768 | 按场景控制 KV Cache |
| Map-Reduce | 长文本分段处理 | 避免单次 prompt 撑满上下文 |
| num_predict 限制 | 动态计算最大输出 token | 防止无限生成 |
| think=False | 批量纠正禁用推理 | 减少 token 消耗 |
| OCR CPU 推理 | RapidOCR ONNX | 不占 GPU 显存 |
| batch_size 控制 | asr_batch_size=3000, 上限 60s | 防 OOM |
| ModelManager 互斥 | acquire() 机制 | ASR 与 TTS 不同时驻留 |
| TTS 批次刷新 | synthesis_batch_chars=1000 | 每批清空激活值缓存 |

---

## 十二、数据模型（Schemas）

### 12.1 任务状态枚举

```
PENDING → PROCESSING_ASR → EXTRACTING_FRAMES → SCANNING_VISUAL
    → CORRECTING → EVALUATING → AUDITING → COMPLETED
                                            ↘ FAILED
```

### 12.2 核心 Schema

| Schema | 关键字段 |
|--------|---------|
| TranscriptEntrySchema | timestamp / timestamp_ms / end_ms / speaker / text / text_corrected |
| TranscriptResponse | transcript: list[TranscriptEntrySchema] + processing_time_ms |
| EvaluationResult | title（纪要标题）/ formatted_content（Markdown 纪要正文）/ truncated（输入被截断）/ degraded_chunks（Map 失败降级的分块数）；后两项由服务端写入，模型输出中的同名字段会被覆盖 |
| ComplianceRule | id / content |
| Violation | id（报告内稳定唯一）/ rule_id / rule_content / timestamp_ms / end_ms / speaker / original_text / reason / reasoning / severity / confidence / source / evidence_url / evidence_text / rule_ref / status |
| ComplianceReport | total_rules / total_segments_checked / total_segments / truncated / total_chunks / failed_chunks / violations[] / summary / compliance_score / source_counts；缺失 id 的违规条目在构造时按顺序补齐，兼容旧数据 |
| TaskResultsResponse | task_id / transcript / evaluation / compliance / has_audio / has_video / **has_synthesis** / keyframe_count / ocr_text_count / visual_event_count |

### 12.3 视觉 Schema

| Schema | 关键字段 |
|--------|---------|
| KeyFrame | timestamp_ms / frame_path / frame_index |
| OCRRecord | timestamp_ms / text / confidence / frame_path / bbox |
| VisualEvent | event_type(face_detected/face_missing) / start_ms / end_ms / confidence / frame_path |

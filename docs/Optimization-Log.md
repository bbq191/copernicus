# Copernicus 关键优化记录

## 一、优化背景

Copernicus 初始版本存在以下问题：

1. **LLM 纠错耗时过长**：44 分钟音频的转写文本（18000+ 字符）送 LLM 纠错需要约 2 小时，原因是串行处理 + Prompt 未约束输出格式导致冗余生成。
2. **FunASR 缺少置信度输出**：Paraformer 模型虽然内部计算了 token 级别的 AM Score，但未暴露给上层调用者，无法实现置信度过滤。
3. **评估功能缺失**：无结构化内容分析能力。

---

## 二、优化前后执行流程对比

### 2.1 优化前流程

```
音频文件
  |
  v
[FunASR 推理] --- Paraformer + VAD + ct-punc（一次性处理）
  |                 - 不输出置信度
  v
全文文本（18000+ 字符，无分句信息）
  |
  v
[字符硬切分] --- chunk_text(chunk_size=800, overlap=50)
  |               - 按字符数强制切分
  |               - 可能切断句子中间
  |               - overlap 区域需去重
  v
N 个文本片段（约 23 个 chunk）
  |
  v
[串行 LLM 纠错] --- for chunk in chunks: await correct(chunk)
  |                   - 逐个等待，无并发
  |                   - Prompt 未约束输出，LLM 附带修正说明
  |                   - 每个 chunk 都送 LLM，无跳过机制
  v
[overlap 去重合并] --- merge_chunks(overlap=50)
  |                     - 简单跳过前 N 字符，可能丢失或重复内容
  v
纠正后全文
  |
  v
（无评估功能）
```

**耗时分布**（44 分钟音频实测）：

| 阶段     | 耗时        | 说明                      |
| -------- | ----------- | ------------------------- |
| FunASR   | ~58 秒      | 性能正常                  |
| LLM 纠错 | ~2 小时     | 串行 + 冗余输出，致命瓶颈 |
| **合计** | **~2 小时** |                           |

### 2.2 优化后流程

```
音频文件
  |
  v
[FunASR 推理] --- Paraformer + VAD + ct-punc（一次性处理）
  |                 - 输出 token_confidence（源码补丁）
  |                 - disable_update=True（离线模式）
  v
全文文本 + 523 个带置信度的 Segment
  |
  v
[置信度过滤] --- confidence >= 0.9 的 Segment 直接保留原文
  |               - 跳过 372/523（71.1%）高置信度分句
  v
151 个低置信度 Segment（分散在 96 个 run 中）
  |
  v
[Run Merge] --- 合并间距 <= 3 的相邻 run
  |              - 96 runs -> 35 runs
  v
[语义分块] --- group_segments(chunk_size=600)
  |             - 按句子边界合并，不切断语义
  |             - 无需 overlap
  |             - 35 runs -> 42 chunks
  v
42 个语义完整的文本 chunk
  |
  v
[并发 LLM 纠错] --- Semaphore(4) + asyncio.gather()
  |                   - 4 路并发，Prompt 约束仅输出正文
  |                   - qwen3 think 标签自动清洗
  v
[按原始索引拼接] --- 高置信度原文 + 低置信度纠正文本
  |                   - 无 overlap，按 Segment 索引精确拼接
  v
纠正后全文（18334 字符）
  |
  v
[内容评估] --- response_format=json_object
  |             - 通用分析 Prompt（非行业绑定）
  |             - 四层 JSON 防御 + 重试机制
  v
结构化评估结果（JSON）
```

**耗时分布**（同一音频实测）：

| 阶段                          | 耗时                     | 说明                       |
| ----------------------------- | ------------------------ | -------------------------- |
| FunASR                        | 57 秒                    | 含置信度提取，耗时基本不变 |
| 置信度过滤 + Run Merge        | < 1 毫秒                 | 纯内存计算                 |
| LLM 纠错（42 chunks, 4 并发） | 128 秒                   | 相比优化前提速 56 倍       |
| 内容评估                      | 30 秒                    | 新增功能                   |
| **合计**                      | **209.5 秒（3.5 分钟）** | **相比优化前提速 34 倍**   |

### 2.3 关键优化效果汇总

| 维度               | 优化前               | 优化后                     | 提升幅度                               |
| ------------------ | -------------------- | -------------------------- | -------------------------------------- |
| 端到端耗时         | ~2 小时              | 3.5 分钟                   | 34x                                    |
| LLM 调用次数       | ~23 次（全量 chunk） | 42 次（仅低置信度）        | 虽然调用次数增加，但单次更快且并发执行 |
| LLM 实际处理文本量 | 18000+ 字符（全量）  | ~7000 字符（38%）          | 节省 62% 算力                          |
| 分块方式           | 字符硬切 + overlap   | 句子边界 + 无 overlap      | 语义完整性显著提升                     |
| 并发度             | 1（串行）            | 4（受控并发）              | 4x                                     |
| 评估能力           | 无                   | 通用内容分析 + JSON 结构化 | 新增                                   |

---

## 三、FunASR 源码改造

### 3.1 Token Confidence 注入（Paraformer 模型补丁）<===== 核心优化

**目标**：从 Paraformer 的 AM Score 中提取逐 token 置信度，供上层进行置信度过滤。

**技术原理**：

Paraformer 在 CIF（Continuous Integrate-and-Fire）解码后，通过 `am_scores`（Attention Memory Scores）保存了每个 token 的对数概率。对其取 `exp` 再取 `max` 即可得到每个 token 的置信度（0~1 区间）。

**补丁文件**：`site-packages/funasr/models/paraformer/model.py`

**具体改动**：

1. 在 `inference` 方法的 greedy 解码分支中（约第 544-545 行），新增置信度提取逻辑：
   - 从 `am_scores` 张量中计算 `torch.exp(am_scores).max(dim=-1)[0]`，得到每个 token 的最大 softmax 概率
   - `am_scores` 是 log_softmax 输出，`exp` 还原为概率值，`max(dim=-1)` 取每个位置的最优 token 概率
   - 将结果转为 Python list 存入局部变量 `_token_confidence`
   - 注意：仅在非 beam-search 路径（greedy 解码）中生效

2. 在结果组装阶段（约第 590-594 行），将 `_token_confidence` 注入到每条结果的字典中：
   - 字段名：`token_confidence`
   - 类型：`list[float]`，长度等于 token 数（不含标点）
   - 使用 `try/except NameError` 保护，因为 beam-search 路径下该变量未定义

**上层对接**：

`asr.py` 中的 `ASRService.transcribe()` 从 FunASR 返回结果中读取 `token_confidence` 字段，传入 `_build_segments()` 进行逐句置信度聚合。

置信度映射的核心难点在于：FunASR 的 ct-punc 模型会在文本中插入标点符号，但这些标点没有对应的 token confidence 值。`_build_segments()` 通过维护一个 `punc_chars` 集合来跳过标点字符，确保 confidence 索引与原始 token 一一对应。

### 3.2 Token Confidence 注入（SeacoParaformer 模型补丁）

**背景**：切换到 `seaco_paraformer_large` 模型后（支持 `sentence_timestamp` + 独立 VAD），原 Paraformer 的 token_confidence 补丁不再生效，因为 SeacoParaformer 有独立的 `inference` 方法。

**补丁文件**：`site-packages/funasr/models/seaco_paraformer/model.py`

**具体改动**（与 3.1 Paraformer 补丁相同的方式）：

1. 在 `inference` 方法的 greedy 解码分支中（`else` 分支，`am_scores.argmax` 之后），新增：
   - `_token_confidence = torch.exp(am_scores).max(dim=-1)[0].tolist()`
   - 原理与 Paraformer 补丁完全相同

2. 在结果组装阶段（`results.append(result_i)` 之前），注入 `token_confidence`：
   - `try: result_i["token_confidence"] = _token_confidence except NameError: pass`

**上层对接**：

`asr.py` 中的 `_build_segments_from_sentence_info()` 接收顶层 `token_confidence` 列表，利用每个 `sentence_info` 项的 `timestamp` 字段长度（等于该句 token 数）对扁平置信度数组进行切片分配，计算每句的平均置信度。

### 3.3 SeacoParaformer 热词缓存优化

**问题**：SeacoParaformer 的 `inference` 方法在每次调用时都执行 `generate_hotwords_list()` 解析热词字符串。当搭配 VAD 模型使用时，长音频被切分为多个片段，每个片段都触发一次 `inference()`，导致热词列表被重复解析数十至上百次（实测 44 分钟音频产生 105 次重复解析）。

**修复**：在 `inference` 方法中添加缓存机制，通过 `_cached_hw_input` 属性记录上一次传入的 hotword 原始值，仅在 hotword 内容发生变化时才重新执行 `generate_hotwords_list()`。

**收益**：热词解析从 N 次（N = VAD 片段数）降至 1 次，消除了不必要的 I/O 和 tokenization 开销。

### 3.4 ModelScope 离线模式

**问题**：FunASR 的 `AutoModel` 默认启用 `check_latest=True`，在构造时会访问 ModelScope 网络检查模型是否有更新。当网络不可用时，`get_or_download_model_dir` 抛出异常被静默捕获，`model_or_path` 仍然保持为 ModelScope ID 字符串（如 `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch`），后续查找 `configuration.json` 失败，最终触发 `AssertionError: ... is not registered`。

**修复**：在 `asr.py` 的 `AutoModel` 构造中添加 `disable_update=True` 参数，跳过在线检查，直接使用本地缓存模型。

---

## 四、Pipeline 架构优化

### 4.1 基于分句的语义分块（替代字符硬切）

**优化前**：`chunk_text()` 按固定字符数（800）硬切文本，辅以 overlap（50 字符）避免语义断裂。存在切分不精准、overlap 去重困难的问题。

**优化后**：利用 FunASR 的 VAD + ct-punc 产出的天然分句结果作为分块边界。`group_segments()` 将多个 Segment 按 `chunk_size` 上限合并为语义完整的 chunk，无需 overlap。

**收益**：

- 分块边界与句子边界对齐，LLM 上下文更连贯
- 无需 overlap 去重，合并逻辑大幅简化
- 纠错质量提升（LLM 看到的是完整句子而非截断片段）

### 4.2 置信度过滤

**原理**：ASR 高置信度的句子（大概率没有识别错误）直接保留原文，仅低置信度句子送 LLM 纠错。

**配置**：`CONFIDENCE_THRESHOLD=0.9`（`.env` 可调）

**实测效果**（基于 44 分钟音频，523 个分句）：

| 指标                 | 数值                               |
| -------------------- | ---------------------------------- |
| 总分句数             | 523                                |
| 高置信度（跳过 LLM） | 372（71.1%）                       |
| 低置信度（送 LLM）   | 151（28.9%）                       |
| 置信度范围           | min=0.7394, max=0.9289, avg=0.9004 |

### 4.3 Run Merge 优化（减少 Chunk 碎片化）<===== 核心优化

**问题**：置信度过滤后，低置信度分句在序列中呈离散分布。151 个低置信度分句产生了 96 个不连续的 run（连续低置信度片段），每个 run 独立成 chunk 会导致 96 次 LLM 调用，chunk 过于碎片化。

**方案**：引入 `confidence_run_merge_gap` 参数（默认 3），当两个相邻 run 之间的高置信度分句数量不超过 gap 值时，将中间的高置信度分句"吞入"相邻 run，合并为一个更大的 run。

**合并流程**：

```
原始 runs: [run_A] --gap=2-- [run_B] --gap=5-- [run_C] --gap=1-- [run_D]
                    <=3 合并          >3 不合并         <=3 合并
合并后:    [run_A+gap+run_B]         [run_C+gap+run_D]
```

**实测效果**：

| 指标         | 优化前 | 优化后 |
| ------------ | ------ | ------ |
| Run 数量     | 96     | 35     |
| Chunk 数量   | 96     | 42     |
| LLM 调用次数 | 96     | 42     |

### 4.4 并发 LLM 调用

**优化前**：串行 `for` 循环逐个 `await _correct_chunk()`。

**优化后**：`asyncio.Semaphore(max_concurrency)` + `asyncio.gather()` 实现受控并发。配合 Ollama 的 `OLLAMA_NUM_PARALLEL=4` 环境变量，服务端代码设置 `CORRECTION_MAX_CONCURRENCY=4`。

---

## 五、Transcript 流水线（说话人 + 时间戳模式）

### 5.1 功能概述

新增 `process_transcript()` 流水线，在原有纯文本纠错基础上，输出带**句子级时间戳**、**说话人标识**、**原文/纠错文本对照**的结构化转写结果。

**输出结构**：

```
TranscriptResult
  transcript: list[TranscriptEntry]
    - timestamp: "MM:SS"
    - timestamp_ms: int
    - speaker: "Speaker 1" / "Speaker 2"
    - text: ASR 原始文本
    - text_corrected: LLM 纠正后文本
  processing_time_ms: float
```

**新增端点**：

- `POST /api/v1/transcribe/transcript` -- 同步返回
- `POST /api/v1/tasks/transcript` -- 异步任务提交

### 5.2 JSON-to-JSON 纠错方案

**动机**：纯文本纠错模式下，LLM 返回的纠正文本无法与原始分句精确对齐。Transcript 模式需要逐句保留时间戳和说话人信息，因此改用 JSON-to-JSON 方案。

**方案设计**：

1. 将需纠错的分句构造为 `[{"id": N, "text": "..."}]` 格式
2. LLM 接收 JSON 数组，逐条修正 `text` 字段，严禁修改 `id`
3. 返回同格式 JSON 数组，通过 `id` 进行 O(1) 哈希回填

**Prompt 规则**（`TRANSCRIPT_SYSTEM_PROMPT`）：

- 禁止修改 id、合并或拆分句子
- 修正同音字、阿拉伯数字格式、标点符号
- 轻度去除无意义重复口语
- 仅输出合法 JSON 数组

**三层 JSON 解析防御**：

1. **严格解析**：`json.loads()` 直接解析
2. **正则提取数组**：`_JSON_ARRAY_RE` 从 LLM 附带的额外文本中提取 `[...]` 部分
3. **逐条正则回捞**：`_extract_entries_by_regex()` 通过 `"id": N, "text": "..."` 模式逐条恢复

实测 32 批次中 4 次触发 JSON 解析失败，正则回捞成功恢复了 3 次（每次 14/15 条），仅 1 次因 LLM 返回空内容而降级为原文。

### 5.3 说话人抖动平滑（Speaker Smoothing）

**问题**：说话人分离模型（CAM++ / speech_campplus）在短语段上偶尔产生"抖动"，即一个短句的 speaker 标签与前后不同，形成 A-B-A 的误判。

**方案**：`smooth_speakers()` 函数在 LLM 纠错之前执行，遍历所有分句，当某个分句满足以下条件时强制修正其 speaker：

- 当前 speaker 与前一句不同
- 前一句与后一句 speaker 相同
- 当前分句时长 < 1500ms

**位置**：`pipeline.py` Step 1，在所有后续处理之前执行。

### 5.4 ASR 预合并（Pre-merge）<===== 核心优化

**问题**：FunASR 的 `sentence_timestamp` 输出粒度极细，44 分钟音频产生 1437 个分句（平均 2-3 秒/句）。这导致：

1. LLM 每批次的上下文碎片化，纠错质量下降
2. 需要 32 个 LLM 批次（batch_size=15），即使 4 路并发也需要 8 轮串行等待
3. 大量细碎分句增加了 JSON 解析失败的概率

**方案**：`pre_merge_segments()` 在 speaker smoothing 之后、LLM 纠错之前执行，将同说话人、短间隔的相邻分句合并为更大的语段。

**合并规则**：

```
对于相邻的 segment[i] 和 segment[i+1]：
  如果 speaker 相同 且 时间间隔 (start[i+1] - end[i]) < 500ms：
    合并文本，更新 end_ms，加权平均置信度
  否则：
    保留为独立段
```

**置信度处理**：合并时按文本长度加权平均，确保长文本的置信度权重更大。

**实测效果**：

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 预合并前 segment 数 | 1437 | 1437 |
| 预合并后 segment 数 | 1437（无预合并） | **144** |
| 需纠错 segment 数 | 477 | **53** |
| LLM 批次数 | 32 | **4** |
| LLM 纠错耗时 | ~11 分钟（含超时重试） | **~42 秒** |

预合并使 segment 数量减少 90%，LLM 批次从 32 降至 4，完全在并发窗口（`max_concurrency=4`）内一次性发出，GPU 利用率接近 100%。

### 5.5 段落后合并（Post-merge）

**目的**：LLM 纠错完成后，将同说话人的连续条目在输出层面合并为段落，减少最终 JSON 条目数，提升阅读体验。

**方案**：`merge_transcript_entries()` 函数在构建 `TranscriptEntry` 列表之前执行，合并规则：

- 同一说话人
- 时间间隔 < 5000ms（因预合并已处理 500ms 以内的细粒度合并，后合并负责更大粒度的段落合并）

**实测效果**：144 个预合并后的 segment 进一步合并为最终输出条目（具体数量取决于说话人切换频率和段落间隔）。

### 5.6 完整 Transcript 流水线执行流程

```
音频文件
  |
  v
[FunASR 推理] --- SeacoParaformer + VAD + PUNC + SPK
  |                 - sentence_timestamp=True
  |                 - token_confidence（源码补丁）
  |                 - speaker diarization（CAM++）
  v
1437 个带时间戳/说话人/置信度的 Segment
  |
  v
[Step 1: Speaker Smoothing] --- 消除短语段说话人抖动
  |
  v
[Step 2: Pre-merge] --- 同说话人 + 间隔 < 500ms 的分句合并
  |                      1437 -> 144 segments
  v
[置信度过滤] --- confidence >= 0.9 的 segment 跳过 LLM
  |               91/144 高置信度跳过
  v
53 个需纠错 segment
  |
  v
[JSON-to-JSON 纠错] --- 4 批次全并发（Semaphore=4）
  |                      三层 JSON 解析防御
  |                      id 哈希回填（O(1)）
  v
[Step 3: Build entries] --- 组装 timestamp + speaker + text + text_corrected
  |
  v
[Step 4: Post-merge] --- 同说话人 + 间隔 < 5s 的条目合并为段落
  |
  v
TranscriptResult（结构化 JSON 输出）
```

### 5.7 耗时分布（44 分钟音频实测，优化后）

| 阶段 | 耗时 | 说明 |
|------|------|------|
| FunASR 推理（CPU） | ~112 秒 | 含 VAD + ASR + PUNC + SPK，当前瓶颈 |
| Speaker Smoothing + Pre-merge | < 1 毫秒 | 纯内存计算 |
| LLM 纠错（4 批次，4 并发） | ~42 秒 | 全并发，无串行等待 |
| Post-merge + 结果组装 | < 1 毫秒 | 纯内存计算 |
| **合计** | **~154 秒（2.6 分钟）** | ASR 占比 73% |

**对比优化前 Transcript 流水线（无预合并）**：

| 指标 | 无预合并 | 有预合并 | 提升 |
|------|---------|---------|------|
| LLM 纠错耗时 | ~11 分钟 | ~42 秒 | **15.7x** |
| 端到端总耗时 | ~13 分钟 | ~2.6 分钟 | **5x** |
| LLM 批次数 | 32 | 4 | 87.5% 减少 |
| JSON 解析失败次数 | 4/32 | 0/4 | 100% 改善 |

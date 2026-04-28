---
title: Copernicus 第三方系统接入指南
author: afu
version: V1.1
date: 2026-04-28
---

# Copernicus 第三方系统接入指南

> 面向需要通过 API 将 Copernicus 能力集成到外部系统的开发者，覆盖标准纪要、合规审核、纯文本评估三项核心功能的完整调用流程。

---

## 一、概述

Copernicus 提供标准 REST API，基于三阶段架构将任务按复杂度分层处理：

| 层级 | 主入口 | 适用场景 |
|---|---|---|
| 存储层 | `PATCH /api/v1/uploads/{hash}` | 大文件分片上传（> 50 MB 推荐） |
| 基础 AI | `POST /api/v1/tasks/standard_minutes` | 转写 + 纠错 + 摘要（90% 场景） |
| 高阶 AI | `POST /api/v1/tasks/compliance_audit` | 多模态合规推理（10% 场景） |

**调用模型**：全部接口采用异步任务模式——提交请求后立即返回 `task_id`，调用方通过轮询接口获取进度和结果。

**服务地址**：默认运行在 `http://<host>:8000`。

**V1.1 主要变化**：
- `standard_minutes` 将转写与摘要合并为一次提交，无需再单独触发评估；
- 合规审核入口统一为 `POST /api/v1/tasks/compliance_audit`；
- 新增分片上传流程，支持断点续传；
- `/health` 新增 VRAM 水位字段。

---

## 二、完整调用链路

### 2.1 全链路（标准纪要 + 合规审核）

```
1. POST /api/v1/tasks/standard_minutes
        上传音视频，返回 task_id
        服务端自动执行：ASR 转写 → 文字纠错 → 智能摘要
        （相同文件自动去重，existing=true 时直接跳至步骤 4）
        |
        v
2. 轮询 GET /api/v1/tasks/{task_id}
        等待 status 变为 completed
        |
        v
3. POST /api/v1/tasks/compliance_audit  （可选）
        传入转写条目 + 规则文件，返回 compliance_task_id
        |
        v
4. 轮询 GET /api/v1/tasks/{compliance_task_id}
        等待 status 变为 completed
        |
        v
5. GET /api/v1/tasks/{task_id}/results
        一次性获取转写、摘要、合规三项结果
```

与 V1.0 相比，评估（摘要）已内置于 `standard_minutes`，调用链路从 7 步缩短为 4 步。

### 2.2 仅获取标准纪要（转写 + 摘要）

```
1. POST /api/v1/tasks/standard_minutes → task_id
2. 轮询 GET /api/v1/tasks/{task_id}，等待 completed
3. GET /api/v1/tasks/{task_id}/results
```

### 2.3 仅获取转写（不含摘要，更快）

适用于只需要转写文本、不需要摘要评分的场景，省去评估阶段，处理速度提升约 30%。

```
1. POST /api/v1/tasks/transcript → task_id
2. 轮询 GET /api/v1/tasks/{task_id}，等待 completed
3. GET /api/v1/tasks/{task_id}/results
```

### 2.4 大文件分片上传

文件大于 50 MB 时推荐使用分片上传，支持断点续传：

```
1. GET /api/v1/uploads/{sha256}?filename=xxx&total_size=yyy
        检查是否已有会话：
          complete=true  → 文件已处理，直接使用返回的 task_id
          offset=n       → 从第 n 字节续传（断点续传）
          offset=0       → 新会话，从头上传
        |
        v
2. 循环 PATCH /api/v1/uploads/{sha256}
        请求头：Content-Range: bytes {start}-{end}/{total}
        请求体：原始二进制（每片建议 5–10 MB）
        |
        v
3. 最后一片响应：complete=true，返回 task_id（已自动提交标准纪要任务）
        |
        v
4. 轮询 GET /api/v1/tasks/{task_id}，等待 completed
5. GET /api/v1/tasks/{task_id}/results
```

### 2.5 仅评估（已有文本）

适合第三方系统已有转写结果、只需要内容评估的场景：

```
1. POST /api/v1/evaluate/transcript/async → task_id（直接传入文本）
2. 轮询 GET /api/v1/tasks/{task_id}，等待 completed
   （result 字段中直接包含评估结果）
```

---

## 三、去重与幂等

服务端在接收文件时自动计算 SHA-256，相同文件重复上传不会触发重复处理，响应中 `existing: true` 标识命中去重。

**可选优化——上传前预检**：对于大文件，可在上传前先查询是否已有处理记录，命中则完全跳过文件传输：

```
GET /api/v1/tasks/lookup?hash={sha256_hex}
    200 existing=true → 直接使用已有 task_id，跳至结果查询
    404              → 继续上传
```

hash 值计算规则：对文件原始二进制内容做 SHA-256，输出 64 位小写十六进制字符串。

**常见错误**

| 错误做法 | 后果 |
|---|---|
| 用文本模式读文件 | Windows 上换行符转换导致 hash 不匹配 |
| 对 base64 内容做 hash | 永远不匹配 |
| 输出大写十六进制 | lookup 始终返回 404 |

---

## 四、接口参考

### 4.1 提交标准纪要任务（主入口）

```
POST /api/v1/tasks/standard_minutes
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| file | 二进制 | 是 | 音频或视频文件，上限 500 MB，支持 mp3/wav/m4a/mp4/mov/mkv 等 |
| hotwords | string | 否 | 热词列表，JSON 数组字符串，如 `["产说会","理财师"]` |
| visual_scan | bool | 否 | 是否提取关键帧并执行 OCR + 人脸检测，仅视频有效，默认 false |
| generate_summary | bool | 否 | 是否在转写完成后自动生成摘要评分，默认 true |

响应字段：`task_id`、`status`（初始为 `pending`）、`existing`（`true` 表示去重命中）。

### 4.2 提交转写任务（轻量，不含摘要）

```
POST /api/v1/tasks/transcript
Content-Type: multipart/form-data
```

参数与 `standard_minutes` 相同，但无 `generate_summary` 字段。
完成后仅有 `transcript` 结果，无 `evaluation`。

### 4.3 分片上传——查询或创建会话

```
GET /api/v1/uploads/{sha256}?filename={filename}&total_size={bytes}
```

| 查询参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| filename | string | 是 | 原始文件名（含扩展名） |
| total_size | int | 是 | 文件总字节数 |
| hotwords | string[] | 否 | 热词列表（Query 数组参数） |
| visual_scan | bool | 否 | 是否执行视觉扫描，默认 false |
| generate_summary | bool | 否 | 是否生成摘要，默认 true |

| 响应字段 | 说明 |
|---|---|
| offset | 当前已接收字节数，客户端从此处续传 |
| complete | true 表示文件已处理完毕 |
| task_id | 仅 complete=true 时存在 |

### 4.4 分片上传——上传数据块

```
PATCH /api/v1/uploads/{sha256}
Content-Range: bytes {start}-{end}/{total}
Content-Type: application/octet-stream
```

每次请求体为一个原始二进制数据块（建议 5–10 MB）。
最后一块校验 SHA-256 通过后自动提交标准纪要任务，响应中包含 `task_id`。

### 4.5 任务状态轮询

```
GET /api/v1/tasks/{task_id}
```

**status 枚举**

| 状态值 | 说明 |
|---|---|
| pending | 已提交，等待处理 |
| processing_asr | ASR 语音识别中 |
| extracting_frames | 提取视频关键帧（视频任务） |
| scanning_visual | 视觉扫描（OCR + 人脸检测） |
| correcting | 文字纠错中，`progress.percent` 有效 |
| evaluating | 摘要评估中，`progress.percent` 有效 |
| auditing | 合规审核中，`progress.percent` 有效 |
| completed | 处理完成 |
| failed | 处理失败，见 `error` 字段 |

轮询间隔建议 2–5 秒，`correcting` / `evaluating` / `auditing` 阶段可用 `progress.percent` 展示进度条。

### 4.6 提交合规审核

```
POST /api/v1/tasks/compliance_audit
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| rules_file | 二进制 | 是 | 规则文件，支持 CSV 或 XLSX，上限 2 MB |
| transcript | string | 是 | 转写条目 JSON 数组字符串（从 results 端点的 `transcript.transcript` 获取） |
| parent_task_id | string | 否 | 关联父任务 ID，结果将持久化到该任务目录，并自动加载对应的 OCR/视觉数据 |

规则文件格式：A 列为规则内容，B–G 列为历史违规案例（Few-Shot），首行为表头。

### 4.7 获取完整结果

```
GET /api/v1/tasks/{task_id}/results
```

| 字段 | 说明 |
|---|---|
| transcript | 完整转写结果，含所有条目和处理耗时 |
| evaluation | 摘要评分结果（`standard_minutes` 自动生成；`transcript` 任务需另行触发） |
| compliance | 合规审核结果（需主动提交 `compliance_audit` 后才有值） |
| has_audio | 是否有音频文件 |
| has_video | 是否为视频任务 |
| keyframe_count | 提取的关键帧数量 |
| ocr_text_count | OCR 识别的文本区块数量 |
| visual_event_count | 视觉事件数量（人脸检测结果） |

### 4.8 更新违规审核状态

人工复核后可批量更新违规条目状态：

```
PATCH /api/v1/tasks/{task_id}/compliance/violations
Content-Type: application/json
```

请求体：`{"updates": [{"index": 0, "status": "confirmed"}, {"index": 1, "status": "rejected"}]}`

`status` 取值：`pending`（待审）/ `confirmed`（已确认）/ `rejected`（已驳回）。
更新立即持久化，页面刷新后状态保留。

### 4.9 重新执行转写

```
POST /api/v1/tasks/{task_id}/rerun-transcript
Content-Type: multipart/form-data
```

对已保存的音频重新执行 ASR + 纠错。原始媒体文件须仍存在（未被 24 小时生命周期清理）。
执行后会清除旧的 `evaluation.json` 和 `compliance.json`，需重新提交相应任务。

### 4.10 重新生成摘要

```
POST /api/v1/tasks/{task_id}/rerun-evaluation
```

无需请求体。基于已有 `transcript.json` 重新生成摘要评分。
适用于更换 LLM 模型后刷新摘要质量。返回子任务 `task_id`，评估完成后结果写入父任务的 `results`。

### 4.11 媒体文件访问

| 端点 | 说明 |
|---|---|
| `GET /api/v1/tasks/{task_id}/media` | 获取原始媒体文件（视频优先，自动回退到音频） |
| `GET /api/v1/tasks/{task_id}/frames/{filename}` | 获取指定关键帧图片，`filename` 来自违规记录的 `evidence_url` |

注意：原始媒体文件在任务完成 24 小时后由系统自动清理，转写/合规 JSON 结果不受影响。

### 4.12 服务健康检查

```
GET /api/v1/health
```

| 响应字段 | 说明 |
|---|---|
| asr_loaded | ASR 模型权重是否在 VRAM 中（合规审核执行期间会短暂为 false） |
| llm_reachable | LLM 服务是否可连接 |
| vram.loaded_models | 当前 ModelManager 管理的已加载模型列表 |
| vram.estimated_used_gb | 已加载模型的估算 VRAM 占用（GB） |
| vram.budget_gb | 配置的 VRAM 预算上限（默认 12.0 GB） |

建议接入前调用确认服务就绪（`asr_loaded=true` 且 `llm_reachable=true`）。

---

## 五、错误处理

| HTTP 状态码 | 含义 | 处理建议 |
|---|---|---|
| 202 | 任务提交成功 | 正常，开始轮询 |
| 400 | 请求格式错误 | 检查 Content-Range 头或请求体是否为空 |
| 404 | 任务 ID 不存在 | 检查 task_id 是否正确，服务重启后磁盘有持久化可恢复 |
| 409 | 分片偏移量冲突 | 重新调用 GET /uploads/{hash} 获取最新 offset 后续传 |
| 413 | 文件过大 | 音视频上限 500 MB，规则文件上限 2 MB |
| 422 | 参数校验失败 | 检查必填字段和格式，`transcript` 必须为合法 JSON 数组 |
| 500 | 服务内部错误 | 查看 `error` 字段，常见原因：ASR 模型未加载、LLM 不可达 |

**上传失败重试**：网络断开无响应时，先调 `GET /tasks/lookup?hash={sha256}` 检查是否已到达服务端；命中则直接轮询，未命中则重传（最多 3 次，间隔 2/4/8 秒）。

**分片上传中断恢复**：中断后直接重新调用 `GET /uploads/{hash}?...`，响应的 `offset` 即为断点位置，从该偏移量继续 PATCH 即可，已传数据不会重复写入。

---

## 六、调用示例

### 6.1 提交标准纪要任务

```
POST /api/v1/tasks/standard_minutes
Content-Type: multipart/form-data

file:             <二进制文件内容>
hotwords:         ["产说会", "理财师"]
generate_summary: true
```

响应（首次提交，202）：

```json
{
  "task_id": "a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d",
  "status": "pending",
  "existing": false
}
```

响应（重复上传，202）：

```json
{
  "task_id": "a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d",
  "status": "completed",
  "existing": true
}
```

### 6.2 轮询任务进度

```
GET /api/v1/tasks/a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d
```

纠错阶段响应：

```json
{
  "task_id": "a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d",
  "status": "correcting",
  "progress": { "current_chunk": 4, "total_chunks": 10, "percent": 48.0 },
  "result": null,
  "error": null
}
```

完成响应：

```json
{
  "task_id": "a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d",
  "status": "completed",
  "progress": { "current_chunk": 10, "total_chunks": 10, "percent": 100.0 },
  "result": { ... },
  "error": null
}
```

失败响应：

```json
{
  "task_id": "a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d",
  "status": "failed",
  "progress": { "current_chunk": 0, "total_chunks": 0, "percent": 0.0 },
  "result": null,
  "error": "ASR 推理超时，请检查 GPU 显存是否充足"
}
```

### 6.3 获取标准纪要结果

```
GET /api/v1/tasks/a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d/results
```

响应（200）：

```json
{
  "task_id": "a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d",
  "transcript": {
    "transcript": [
      {
        "timestamp":      "00:00:01",
        "timestamp_ms":   1200,
        "end_ms":         4800,
        "speaker":        "SPEAKER_00",
        "text":           "各位来宾大家下午好我是本次产说会的主持人",
        "text_corrected": "各位来宾大家下午好，我是本次产说会的主持人"
      }
    ],
    "processing_time_ms": 18400
  },
  "evaluation": {
    "meta": {
      "title": "保险产品说明会",
      "category": "金融产品推介",
      "keywords": ["产说会", "保险责任", "收益率"]
    },
    "scores": {
      "logic": 78,
      "info_density": 82,
      "expression": 75,
      "total": 79
    },
    "analysis": {
      "main_points": ["产品收益说明", "保障责任介绍", "投保注意事项"],
      "key_data": ["年化收益 3.5%", "保障期 20 年"],
      "sentiment": "正面，整体表达积极"
    },
    "summary": "本次产说会主要介绍了某款终身寿险产品..."
  },
  "compliance": null,
  "has_audio": true,
  "has_video": false,
  "keyframe_count": 0,
  "ocr_text_count": 0,
  "visual_event_count": 0
}
```

### 6.4 提交合规审核

```
POST /api/v1/tasks/compliance_audit
Content-Type: multipart/form-data

rules_file:     <CSV 或 XLSX 文件二进制>
transcript:     [{"timestamp":"00:00:01","timestamp_ms":1200,"end_ms":4800,
                  "speaker":"SPEAKER_00","text":"...","text_corrected":"..."}]
parent_task_id: a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d
```

响应（202）：

```json
{
  "task_id": "d7e2b1f9c4a083e6b5d2c8f1a3e7b904",
  "status": "pending",
  "existing": false
}
```

### 6.5 合规审核结果（从父任务 results 读取）

再次调用 `GET /api/v1/tasks/{parent_task_id}/results`，`compliance` 字段包含：

```json
{
  "rules": [
    { "id": 1, "content": "禁止承诺保证收益" }
  ],
  "report": {
    "total_rules": 1,
    "total_segments_checked": 24,
    "compliance_score": 72,
    "summary": "发现 1 处高风险违规，主要集中在收益承诺表述...",
    "source_counts": { "transcript": 1, "ocr": 0, "vision": 0 },
    "violations": [
      {
        "rule_id": 1,
        "rule_content": "禁止承诺保证收益",
        "timestamp_ms": 18300,
        "end_ms": 21500,
        "speaker": "SPEAKER_01",
        "original_text": "这款产品每年保证给您 3.5% 的收益",
        "reason": "使用「保证」承诺固定收益，违反监管规定",
        "reasoning": "步骤 1：原文含「保证」...\n步骤 2：对照规则 1...\n结论：高风险违规",
        "severity": "high",
        "confidence": 0.94,
        "source": "transcript",
        "evidence_url": null,
        "evidence_text": null,
        "rule_ref": "规则 1",
        "status": "pending"
      }
    ]
  },
  "processing_time_ms": 34200
}
```

### 6.6 完整调用时序

**标准纪要（首次上传）**

```
第三方系统                               Copernicus API
    |                                         |
    |-- POST /tasks/standard_minutes -------->|
    |<-- 202 {task_id: "abc"} ---------------|
    |                                         |
    |-- GET /tasks/abc ---------------------->| (correcting, 45%)
    |<-- 200 {status: "correcting"} ---------|
    |                                         |
    |-- GET /tasks/abc ---------------------->| (evaluating, 90%)
    |<-- 200 {status: "evaluating"} ---------|
    |                                         |
    |-- GET /tasks/abc ---------------------->| (completed)
    |<-- 200 {status: "completed"} ----------|
    |                                         |
    |-- GET /tasks/abc/results ------------->|
    |<-- 200 {transcript, evaluation} -------|
```

**全链路（含合规审核）**

```
第三方系统                               Copernicus API
    |                                         |
    |-- POST /tasks/standard_minutes -------->|
    |<-- 202 {task_id: "abc"} ---------------|
    |                                         |
    |-- GET /tasks/abc ---------------------->| (completed)
    |<-- 200 {status: "completed"} ----------|
    |                                         |
    |-- POST /tasks/compliance_audit -------->|
    |   (transcript + rules_file)             |
    |<-- 202 {task_id: "def"} ---------------|
    |                                         |
    |-- GET /tasks/def ---------------------->| (auditing)
    |<-- 200 {status: "auditing"} -----------|
    |                                         |
    |-- GET /tasks/def ---------------------->| (completed)
    |<-- 200 {status: "completed"} ----------|
    |                                         |
    |-- GET /tasks/abc/results ------------->|
    |<-- 200 {transcript,                    |
    |         evaluation, compliance} -------|
```

**重复上传（自动去重）**

```
第三方系统                               Copernicus API
    |                                         |
    |-- POST /tasks/standard_minutes -------->|
    |<-- 202 {task_id: "abc",                |
    |         existing: true} ---------------| (已有结果，跳过处理)
    |                                         |
    |-- GET /tasks/abc/results ------------->|
    |<-- 200 {transcript, evaluation} -------|
```

---

## 七、注意事项

| 事项 | 说明 |
|---|---|
| 服务就绪等待 | ASR 模型首次启动加载需数十秒，建议接入前调 `/health` 确认 `asr_loaded=true` |
| asr_loaded 短暂为 false | 合规审核执行期间系统主动卸载 ASR 权重以释放 VRAM，下一次转写任务自动重载，无需干预 |
| GPU 串行机制 | ASR 推理串行执行，多任务并发提交时后续任务排队等待前一任务 ASR 阶段完成 |
| 摘要自动生成 | `standard_minutes` 默认 `generate_summary=true`，评估与转写在同一任务内完成，无需额外调用 |
| 文件去重 | 直接重传相同文件不会触发重复处理，`existing=true` 时直接查询已有结果即可 |
| 媒体文件生命周期 | 原始音视频文件在任务完成 24 小时后自动清理，转写/评估/合规 JSON 结果永久保留 |
| 任务持久化 | 结果持久化在服务器 `uploads/{task_id}/` 目录，服务重启后仍可通过 results 端点访问 |
| 任务内存上限 | 内存中最多保留 500 个任务，超出后已完成任务淘汰，但磁盘结果仍可访问 |
| 规则文件编码 | CSV 自动尝试 utf-8-sig / gbk / gb18030 三种编码，XLSX 无需特别处理 |
| 合规 transcript 参数 | 需将 results 端点返回的 `transcript.transcript` 数组序列化为 JSON 字符串传入 |

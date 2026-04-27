# Copernicus 第三方系统接入指南

> 作者: afu
>
> 面向需要通过 API 将 Copernicus 能力集成到外部系统的开发者，覆盖转文字、内容评估、合规审核三项核心功能的完整调用流程。

---

## 一、概述

Copernicus 提供标准 REST API，支持第三方系统以全异步方式调用三项核心能力：

| 能力     | 说明                                                                            |
| -------- | ------------------------------------------------------------------------------- |
| 转文字   | 上传音频或视频文件，经 ASR + 四阶段文本纠正后输出带时间戳和说话人标签的转写条目 |
| 内容评估 | 基于转写文本生成智能摘要，包含多维评分、主要观点、关键数据和情感倾向            |
| 合规审核 | 结合转写条目与规则文件，通过 CoT 推理检测违规，输出带置信度的违规报告           |

**调用模型**: 全部接口采用异步任务模式——提交请求后立即返回 `task_id`，调用方通过轮询接口获取进度和结果。

**服务地址**: 默认运行在 `http://<host>:8000`。

---

## 二、完整调用链路

### 2.1 全链路（转文字 + 评估 + 合规审核）

```
1. POST /api/v1/tasks/transcript
        上传音视频文件，返回 task_id
        （服务端自动计算 SHA-256，相同文件直接返回已有任务）
        |
        v
2. 轮询 GET /api/v1/tasks/{task_id}
        等待 status 变为 completed（转写 + 纠错完成）
        |
        v
3. POST /api/v1/tasks/{task_id}/rerun-evaluation
        提交评估任务，返回 eval_task_id
        |
        v
4. 轮询 GET /api/v1/tasks/{eval_task_id}
        等待 status 变为 completed（摘要 + 评分完成）
        |
        v
5. POST /api/v1/compliance/audit/async（可选）
        传入转写条目 + 规则文件，返回 compliance_task_id
        |
        v
6. 轮询 GET /api/v1/tasks/{compliance_task_id}
        等待 status 变为 completed（合规审核完成）
        |
        v
7. GET /api/v1/tasks/{task_id}/results
        一次性获取转写、评估、合规三项结果
```

**评估不自动触发**: 转写完成后，评估需要调用方主动发起（步骤 3）。合规审核同样需要主动发起（步骤 5）。

### 2.2 仅转文字

```
1. POST /api/v1/tasks/transcript → task_id
2. 轮询 GET /api/v1/tasks/{task_id}，等待 completed
3. GET /api/v1/tasks/{task_id}/results
```

### 2.3 仅评估（已有文本）

适合第三方系统已有自己的转写结果，只需要内容评估的场景。

```
1. POST /api/v1/evaluate/transcript/async → task_id（直接传入文本）
2. 轮询 GET /api/v1/tasks/{task_id}，等待 completed
   （result 字段中直接包含评估结果）
```

---

## 三、去重与幂等

服务端在接收文件时自动计算 SHA-256，相同文件重复上传不会触发重复处理，响应中 `existing: true` 标识命中去重。

**可选优化——上传前预检**: 对于大文件，可在上传前先查询是否已有处理记录，命中则完全跳过文件传输：

```
GET /api/v1/tasks/lookup?hash={sha256_hex}
    200 existing=true → 直接使用已有 task_id，跳至结果查询
    404              → 继续上传
```

hash 值计算规则：对文件原始二进制内容做 SHA-256，输出 64 位小写十六进制字符串。

**常见错误**

| 错误做法              | 后果                             |
| --------------------- | -------------------------------- |
| 用文本模式读文件      | Windows 上换行符转换导致 hash 不匹配 |
| 对 base64 内容做 hash | 永远不匹配                       |
| 输出大写十六进制      | lookup 始终返回 404              |

---

## 四、接口参考

### 4.1 提交转写任务

```
POST /api/v1/tasks/transcript
Content-Type: multipart/form-data
```

| 字段        | 类型   | 必填 | 说明                                                                    |
| ----------- | ------ | ---- | ----------------------------------------------------------------------- |
| file        | 二进制 | 是   | 音频或视频文件，上限 500MB，支持 mp3/wav/m4a/mp4/mov/mkv 等常见格式   |
| hotwords    | string | 否   | 热词列表，JSON 数组字符串，如 `["产说会","理财师"]`                    |
| visual_scan | bool   | 否   | 是否启用视觉扫描（关键帧 OCR + 人脸检测），仅对视频有效，默认 false    |

响应字段：`task_id`、`status`（初始为 pending）、`existing`（true 表示去重命中）。

### 4.2 任务状态轮询

```
GET /api/v1/tasks/{task_id}
```

**status 枚举**

| 状态值            | 说明                                   |
| ----------------- | -------------------------------------- |
| pending           | 已提交，等待处理                       |
| processing_asr    | ASR 语音识别中                         |
| extracting_frames | 提取视频关键帧（视频任务）             |
| scanning_visual   | 视觉扫描（OCR + 人脸检测）             |
| correcting        | 四阶段文本纠正中，progress.percent 有效 |
| evaluating        | 内容评估中，progress.percent 有效      |
| auditing          | 合规审核中                             |
| completed         | 处理完成                               |
| failed            | 处理失败，见 error 字段                |

轮询间隔建议 2-5 秒，`correcting` 和 `evaluating` 阶段可用 `progress.percent` 展示进度。

### 4.3 提交评估任务

```
POST /api/v1/tasks/{task_id}/rerun-evaluation
```

无需请求体。返回 `eval_task_id`，轮询该 task_id 至 completed 后，评估结果自动写入父任务的 results。

### 4.4 提交合规审核

```
POST /api/v1/compliance/audit/async
Content-Type: multipart/form-data
```

| 字段           | 类型   | 必填 | 说明                                                      |
| -------------- | ------ | ---- | --------------------------------------------------------- |
| rules_file     | 二进制 | 是   | 规则文件，支持 CSV 或 XLSX，上限 2MB                     |
| transcript     | string | 是   | 转写条目 JSON 数组字符串（从 results 端点的 transcript.transcript 获取）|
| parent_task_id | string | 否   | 关联父任务 ID，结果将持久化到该任务目录                   |

规则文件格式：A 列为规则内容，B-G 列为历史违规案例（Few-Shot），首行为表头。

### 4.5 获取完整结果

```
GET /api/v1/tasks/{task_id}/results
```

| 字段               | 说明                                       |
| ------------------ | ------------------------------------------ |
| transcript         | 完整转写结果，含所有条目和处理耗时         |
| evaluation         | 内容评估结果（需主动触发评估后才有值）     |
| compliance         | 合规审核结果（需主动触发审核后才有值）     |
| has_audio          | 是否有音频文件                             |
| has_video          | 是否为视频任务                             |
| keyframe_count     | 提取的关键帧数量                           |
| ocr_text_count     | OCR 识别的文本区块数量                     |
| visual_event_count | 视觉事件数量（人脸检测结果）               |

### 4.6 更新违规审核状态

人工复核后可批量更新违规条目状态：

```
PATCH /api/v1/tasks/{task_id}/compliance/violations
Content-Type: application/json
```

请求体：`{"updates": [{"index": 0, "status": "confirmed"}, {"index": 1, "status": "rejected"}]}`

`status` 取值：`pending` / `confirmed` / `rejected`。

### 4.7 媒体文件访问

| 端点                                          | 说明                                             |
| --------------------------------------------- | ------------------------------------------------ |
| GET /api/v1/tasks/{task_id}/media             | 获取原始媒体文件（视频优先，自动回退到音频）     |
| GET /api/v1/tasks/{task_id}/frames/{filename} | 获取指定关键帧图片，filename 来自违规记录的 evidence_url |

### 4.8 服务健康检查

```
GET /api/v1/health
```

返回 `asr_loaded`（ASR 模型是否就绪）和 `llm_reachable`（LLM 服务是否可连接）。建议接入前调用确认服务就绪。

---

## 五、错误处理

| HTTP 状态码 | 含义             | 处理建议                                               |
| ----------- | ---------------- | ------------------------------------------------------ |
| 202         | 任务提交成功     | 正常，开始轮询                                         |
| 404         | 任务 ID 不存在   | 检查 task_id 是否正确，服务重启后磁盘有持久化可恢复    |
| 413         | 文件过大         | 音视频上限 500MB，规则文件上限 2MB                     |
| 422         | 参数校验失败     | 检查必填字段和格式，transcript 必须为合法 JSON 数组    |
| 500         | 服务内部错误     | 查看 error 字段，常见原因：ASR 模型未加载、LLM 不可达  |

**上传失败重试**: 网络断开无响应时，先调 `GET /tasks/lookup?hash={sha256}` 检查是否已到达服务端；命中则直接轮询，未命中则重传（最多 3 次，间隔 2/4/8 秒）。不计算 hash 时可直接重传，服务端去重保证不会重复处理。

---

## 六、调用示例

### 6.1 提交转写

```
POST /api/v1/tasks/transcript
Content-Type: multipart/form-data

file:      <二进制文件内容>
hotwords:  ["产说会", "理财师"]
```

响应（首次，202）：

```
{
  "task_id": "a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d",
  "status": "pending",
  "existing": false
}
```

响应（重复上传，202）：

```
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

处理中响应：

```
{
  "task_id": "a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d",
  "status": "correcting",
  "progress": { "current_chunk": 4, "total_chunks": 10, "percent": 48.0 },
  "result": null,
  "error": null
}
```

完成响应：

```
{
  "task_id": "a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d",
  "status": "completed",
  "progress": { "current_chunk": 10, "total_chunks": 10, "percent": 100.0 },
  "result": { ... },
  "error": null
}
```

失败响应：

```
{
  "task_id": "a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d",
  "status": "failed",
  "progress": { "current_chunk": 0, "total_chunks": 0, "percent": 0.0 },
  "result": null,
  "error": "ASR 推理超时，请检查 GPU 显存是否充足"
}
```

### 6.3 提交评估

```
POST /api/v1/tasks/a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d/rerun-evaluation
```

响应（202）：

```
{
  "task_id": "b9c3d2e1f0a4857c6b3d2e8f1a4c7b90",
  "status": "pending",
  "existing": false
}
```

### 6.4 获取完整结果

```
GET /api/v1/tasks/a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d/results
```

响应（200）：

```
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

### 6.5 提交合规审核

```
POST /api/v1/compliance/audit/async
Content-Type: multipart/form-data

rules_file:     <CSV 或 XLSX 文件二进制>
transcript:     [{"timestamp":"00:00:01","timestamp_ms":1200,"end_ms":4800,
                  "speaker":"SPEAKER_00","text":"...","text_corrected":"..."}]
parent_task_id: a3f8c1d2e5b04f9c8a7d6e3b2c1f0a9d
```

响应（202）：

```
{
  "task_id": "d7e2b1f9c4a083e6b5d2c8f1a3e7b904",
  "status": "pending",
  "existing": false
}
```

### 6.6 合规审核结果（从 results 读取）

```
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

### 6.7 完整调用时序

**首次上传**

```
第三方系统                           Copernicus API
    |                                     |
    |-- POST /tasks/transcript ---------->|
    |<-- 202 {task_id: "abc"} -----------|
    |                                     |
    |-- GET /tasks/abc ------------------>| (correcting, 45%)
    |<-- 200 {status: "correcting"} ------|
    |                                     |
    |-- GET /tasks/abc ------------------>| (completed)
    |<-- 200 {status: "completed"} -------|
    |                                     |
    |-- POST /tasks/abc/rerun-evaluation->|
    |<-- 202 {task_id: "def"} -----------|
    |                                     |
    |-- GET /tasks/def ------------------>| (evaluating)
    |<-- 200 {status: "evaluating"} ------|
    |                                     |
    |-- GET /tasks/def ------------------>| (completed)
    |<-- 200 {status: "completed"} -------|
    |                                     |
    |-- GET /tasks/abc/results ---------->|
    |<-- 200 {transcript, evaluation} ----|
```

**重复上传（自动去重）**

```
第三方系统                           Copernicus API
    |                                     |
    |-- POST /tasks/transcript ---------->|
    |<-- 202 {task_id: "abc",            |
    |         existing: true} -----------| (已有结果，跳过处理)
    |                                     |
    |-- GET /tasks/abc/results ---------->|
    |<-- 200 {transcript, evaluation} ----|
```

---

## 七、注意事项

| 事项             | 说明                                                                                         |
| ---------------- | -------------------------------------------------------------------------------------------- |
| 服务就绪等待     | ASR 模型首次启动加载需数十秒，建议接入前调 `/health` 确认就绪                               |
| GPU 独占机制     | ASR 推理串行执行，多任务并发提交时后续任务排队等待前一任务 ASR 阶段完成                     |
| 评估不自动触发   | 转写完成后评估需主动调用 `POST /tasks/{task_id}/rerun-evaluation`，合规审核同理              |
| 文件去重         | 直接重传相同文件不会触发重复处理，`existing: true` 时直接查询已有结果即可                   |
| 任务持久化       | 结果持久化在服务器 `uploads/{task_id}/` 目录，服务重启后仍可通过 results 端点访问历史任务   |
| 任务内存上限     | 内存中最多保留 500 个任务，超出后已完成任务淘汰，但磁盘结果仍可访问                         |
| 规则文件编码     | CSV 自动尝试 utf-8-sig / gbk / gb18030 三种编码，XLSX 无需特别处理                          |
| 合规 transcript  | `transcript` 参数需将 results 端点返回的 `transcript.transcript` 数组序列化为 JSON 字符串   |

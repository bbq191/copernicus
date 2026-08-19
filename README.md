# Copernicus

音视频智能听写与合规审核工作台。上传会议音视频后自动完成：ASR 语音识别（含说话人分离）→ 四阶段文本纠正 → 模板驱动的会议纪要生成，并可选执行多源合规审核（语音 + OCR + 视觉）与多说话人 TTS 音频重塑。

**技术栈**：FastAPI + FunASR (Paraformer / SenseVoice) + Ollama/DeepSeek LLM + ChatTTS + RapidOCR + YOLO ｜ React 19 + TypeScript + Vite + Zustand + DaisyUI

## 仓库结构

```
backend/    FastAPI 后端（Python ≥ 3.12，pyenv 管理）
frontend/   React 前端（Vite，开发端口 3000，代理 /api → 8000）
docs/       项目文档（见下方导航）
logs/       开发日志（每 8 小时一个文件）
```

## 快速开始

- **后端**：进入 `backend/`，按 `.env.example` 准备 `.env`（LLM 地址、ASR 模式等），模型放入 `models/`（可用 `scripts/download_models.py` 预下载），运行 `python run_dev.py`（默认 8000 端口）。
- **前端**：进入 `frontend/`，`pnpm install && pnpm dev`（默认 3000 端口，已配置 API 代理）。
- **生产部署**：见 `docs/prob/deployment-centos.md`（Rocky Linux 从裸机到上线的完整步骤）。

## 文档导航（docs/）

### docs/intro/ — 现状介绍（与代码同步维护，首选阅读）

| 文档 | 内容 | 适合谁 |
|---|---|---|
| `features.md` | 功能清单：从上传到纪要/合规/TTS 的完整功能链路 + API 端点汇总 | 所有人，**建议第一篇读** |
| `backend-architecture.md` | 后端架构：Pipeline 九阶段编排、服务层、LLM 集成、配置体系、容错与显存策略 | 后端开发 |
| `frontend-architecture.md` | 前端架构：路由/布局、组件层级、Zustand 状态、数据流、关键设计决策 | 前端开发 |
| `third-party-integration.md` | 第三方系统 API 接入指南：调用链路、接口参考、错误处理、示例 | 外部集成方 |
| `concurrency.md` | 多任务并发模型：各阶段锁与信号量、时序分析、推荐并发策略 | 运维 / 性能调优 |
| `capacity-limits.md` | 压力极限：单文件大小、音频时长、文本上限等安全上限与调优建议 | 运维 / 性能调优 |

### docs/prob/ — 部署运维（本地文档，未纳入 git）

| 文件 | 内容 |
|---|---|
| `deployment-centos.md` | Rocky Linux 生产部署指南（驱动/CUDA、模型、Ollama、systemd、Nginx）|
| `copernicus-backend.service` / `copernicus.conf` | systemd 单元与 Nginx 配置样例 |

### docs/study/ — 学习笔记

| 文件 | 内容 |
|---|---|
| `copernicus_study.md` | 以本项目源码为教材的 Python 教程（13 课 + 工程技巧）|
| `copernicus_frontend_study.md` | 以本项目源码为教材的 React/TypeScript 教程 |

### docs/back/、docs/front/ — 历史设计归档（本地文档，未纳入 git）

早期设计方案、优化记录与阶段计划（`back/1.0` 为初版架构与各专项优化记录，`back/1.1` 为三层架构改造计划，`front/` 为前端初期设计方案）。**内容反映当时的设计状态，部分技术细节与当前实现不一致**（如早期方案中的 React 18、MD5 幂等等），仅作演进过程参考，不要当作现状文档使用。

## 推荐阅读路径

- **新成员上手**：`intro/features.md` → 按方向读 `intro/backend-architecture.md` 或 `intro/frontend-architecture.md`
- **外部系统对接**：`intro/third-party-integration.md`（配合 `intro/features.md` 的端点汇总）
- **部署与容量规划**：`prob/deployment-centos.md` → `intro/capacity-limits.md` → `intro/concurrency.md`
- **了解设计演进**：`back/1.0/ARCHITECTURE.md` → `back/1.1/intro.md` → `back/1.0/Optimization-Log.md`

# 首次配置 notify-afu 任务单唤醒工作流

- Task ID: 2026-11-12-notify-afu-setup
- 负责 bot: copernicus
- 状态: pending
- 执行方: cloud-agent（box 上暂无 GitHub 推送凭据，改由 Cursor 云端代理开分支和 PR）
- 分支: chore/notify-afu（从最新 master 切出）
- 更新时间: 2026-11-12T14:36+08:00
- 引用: 无

## 需求原文
> 【工作流优化 · 首次配置 notify-afu】用户要求给你的仓库新建 `.github/workflows/notify-afu.yml`（目前没有）。正本模板：`~/Documents/ikate/Projects/_templates/notify-afu.yml`，复制到上述路径即可。要点：仅 done/blocked 或 `.agy.md` 改动才 POST；需要 Secrets `AFU_WEBHOOK_URL` / `AFU_WEBHOOK_TOKEN`——你不要写 Secret 值，在任务单结果里提醒用户从 Jarvis「任务单唤醒路由」面板复制 Webhook URL 和 key 填入。请开任务单（建议 `2026-11-12-notify-afu-setup`），验收后 push 合并。（经 Jarvis 转达）

## 输入
- 背景：见库里 Projects/copernicus/context.md 与 Projects/工作流.md「唤醒配置 · A」
- 涉及文件：`.github/workflows/notify-afu.yml`（新增，原样复制模板）；`.dev/tasks/2026-11-12-notify-afu-setup.md`（新增，本任务单）

## 约束
- 不做：不写任何 Secret 值；不改 `ci.yml` 或其他文件
- 提交信息用中文 + 前缀，不加 Co-Authored-By
- 风险点：无（只新增一个仅在 `.dev/tasks/**` 变动时触发、权限 contents: read 的工作流）

## 分步任务
1. [x] 新增 `.github/workflows/notify-afu.yml`，内容与模板逐字节一致
2. [x] 新增本任务单

## 验收标准
- [ ] 工作流文件与模板逐字节一致
- [ ] 只新增上述两个文件
- [ ] Secrets 未配置时工作流跳过 POST 并成功退出

## 结果
- 执行方：Cursor 云端代理
- 偏离：执行方不是 opencode-local / box-agent，原因是 box 暂无 GitHub 推送凭据
- 未完成：**仓库 Secrets 待用户填写**——在 GitHub 仓库 Settings → Secrets and variables → Actions 新增 `AFU_WEBHOOK_URL`、`AFU_WEBHOOK_TOKEN`，值从 Jarvis「任务单唤醒路由」面板复制（token 为原始值，不含 Bearer 前缀）

## 审查
<!-- 负责 bot 填写 -->
- 验收：暂停。模板正本存在新分支首次 push 误发历史回执的问题，等 Jarvis 修好正本后更新工作流再验收。
- 合并：

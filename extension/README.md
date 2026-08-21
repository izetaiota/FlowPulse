# MetaCorpus 元语助手 Chrome Extension

MetaCorpus（元语助手）——抖音小红书元数据解析，AI 语料提取工具。一键解析短视频、笔记，提取文案字幕与完整元数据，输出结构化语料供给 AI 分析。

这是配套后端 API 的 Chrome Manifest V3 侧边栏客户端。

当前版本支持：

- 检查本地 API 连接状态。
- 获取当前抖音标签页 URL。
- 粘贴抖音链接或完整分享文案。
- 创建转写任务。
- 跟踪任务状态和进度。
- 在侧边栏查看结构化转写结果。
- 复制转写全文。
- 按视频聚合最近任务并展示尝试、失败次数。
- 查看失败原因并重新执行任务。
- 根据后端能力标记可用和未配置的转写引擎。
- 下载 JSON、SRT 和 Markdown 文本产物。
- 侧边栏关闭后通过 `chrome.alarms` 同步运行中任务。

## 开发

```powershell
cd extension
npm.cmd install
npm.cmd run build
```

构建产物位于 `extension/dist`。

## 在 Chrome 中加载

1. 启动后端：

   ```powershell
   .\.venv-dev\Scripts\python.exe -m uvicorn douyin_transcribe.main:app `
     --host 127.0.0.1 `
     --port 8000
   ```

2. 打开 `chrome://extensions`。
3. 开启“开发者模式”。
4. 点击“加载已解压的扩展程序”。
5. 选择本项目的 `extension/dist` 目录。
6. 点击工具栏中的扩展图标，打开侧边栏。

## 小红书面板

侧边栏顶部提供「抖音转写 / 小红书」两个标签页。小红书面板支持：

- **一键获取 Cookie 登录**：从登录态 Cookie 直接登录，无需扫码。
- **扫码登录**：在面板内展示二维码并轮询状态，扫码确认后自动登录。
- **搜索笔记**：关键词搜索并列出结果，可点击打开原文。
- **笔记详情**：粘贴笔记链接，查看标题、作者、点赞、正文、视频地址等结构化信息。
- **下载 / 导出任务**：按笔记链接 / 用户主页 / 关键词创建抓取任务，输出媒体与 Excel，面板内查看进度并下载产物。

两种登录方式（扫码 / Cookie）均已真实账号实测可用，按习惯任选其一。

### 扫码登录

点击「扫码登录」→ 面板展示二维码 → 用小红书 App 扫码并在手机确认 → 自动完成登录。

### Cookie 登录

Cookie 登录需要合并两类 Cookie 才完整：

- HttpOnly 的服务端 Cookie（如 `web_session`）——由 `chrome.cookies` 读取；
- 前端 JS 写入的 Cookie（如 `a1`、`webId`、`gid`）——由 **当前小红书标签页的 `document.cookie`** 读取。

因此使用前请：

1. 在浏览器**完整登录** `www.xiaohongshu.com`（能看到自己头像，非游客态）；
2. **保持这个已登录的小红书标签页处于打开状态**（扩展需要从它读取 `a1` 等 JS Cookie）；
3. 打开侧边栏 → 小红书 → 点击「一键获取 Cookie 登录」。

> **验证结论（真实账号实测通过）**：扫码登录、Cookie 登录均可完成登录；登录状态 → 搜索笔记 → 笔记详情 全链路正常返回真实数据。

新增权限：`cookies`、`scripting`、`tabs` 及 `https://*.xiaohongshu.com/*` Host Permission（仅用于读取登录态 Cookie）。修改后需在 `chrome://extensions` 点击该扩展的「刷新」并重新加载 `dist`（会提示确认新增权限）。

## 本地 API

当前版本只允许连接：

```text
http://127.0.0.1:8000
```

这是有意的安全限制，并与 `manifest.json` 中的 Host Permission 保持一致。

设置页已经预留配对 Token。后端鉴权完成前，该字段可以留空。

## 检查

```powershell
npm.cmd run typecheck
npm.cmd run build
```

生产构建必须包含：

```text
dist/
  manifest.json
  service-worker.js
  sidepanel.html
  assets/
```

# Douyin Transcribe Chrome Extension

这是 Douyin Transcribe API 的 Chrome Manifest V3 侧边栏客户端。

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

# Chrome 扩展交互端需求与实施方案

## 1. 文档目的

本文档定义 Douyin Transcribe API 的 Chrome 扩展交互端需求、总体架构、接口调整、实施阶段和验收标准。

目标不是单独增加一个展示页面，而是建立完整的数据闭环：

```text
浏览器采集
  -> 创建转写任务
  -> 跟踪处理进度
  -> 查看和校对结构化结果
  -> 下载、复制或导出
  -> 保留任务和导出记录
```

本文档以本地单用户场景为第一实施目标，同时为后续远程服务、多用户和第三方平台导出预留扩展点。

## 2. 当前系统基础

现有后端已经具备以下能力：

- 接收抖音分享链接或完整分享文案。
- 创建异步转写任务。
- 解析抖音页面和视频元数据。
- 优先提取内嵌字幕。
- 使用听悟、Whisper、SenseVoice 或 OpenAI-compatible API 转写。
- 生成 JSON、SRT 和 Markdown 产物。
- 查询任务、重试任务和下载产物。

当前接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/v1/tasks/transcribe` | 创建任务 |
| `GET` | `/api/v1/tasks/{task_id}` | 查询任务 |
| `POST` | `/api/v1/tasks/{task_id}/retry` | 重试任务 |
| `GET` | `/api/v1/tasks/{task_id}/artifacts` | 获取产物列表 |
| `GET` | `/api/v1/tasks/{task_id}/artifacts/{name}` | 下载产物 |
| `GET` | `/health/live` | 存活检查 |
| `GET` | `/health/ready` | 就绪检查 |

要形成稳定的前端产品，还缺少：

- API 客户端鉴权。
- 任务列表和分页。
- 稳定的结构化结果接口。
- 幂等创建任务。
- 任务取消和删除。
- 服务重启后的任务恢复。
- 导出状态和导出适配器。
- 面向扩展端的能力发现接口。

## 3. 产品目标

### 3.1 第一阶段目标

用户在 Chrome 中浏览抖音页面或拿到分享文案后，可以：

1. 点击扩展图标打开侧边栏。
2. 自动获取当前标签页 URL，或手动粘贴分享文案。
3. 选择转写引擎和输出格式。
4. 创建任务并看到实时进度。
5. 在侧边栏中查看视频信息、全文和分段字幕。
6. 复制全文或 Markdown。
7. 下载 JSON、SRT 和 Markdown。
8. 查看最近任务，对失败任务执行重试。
9. 在后端离线时看到明确的连接和恢复提示。

### 3.2 后续目标

- 编辑和校对转写文本。
- 标签、收藏和备注。
- 导出到 Obsidian、Notion、飞书或自定义 Webhook。
- 浏览器通知。
- 多设备或远程服务。
- 多用户身份和权限。

### 3.3 非目标

第一版不实施：

- 自动采集完整浏览历史。
- 在用户无操作时批量抓取抖音页面。
- 依赖抖音 DOM 的复杂 Content Script。
- Native Messaging 安装器。
- Redis、Celery 或 Kubernetes。
- 在扩展中保存第三方平台的长期密钥。

## 4. 技术决策

### 4.1 扩展形态

采用：

- Chrome Manifest V3。
- Chrome Side Panel 作为主界面。
- Extension Service Worker 作为统一通信和后台同步层。
- `chrome.storage` 保存设置、任务索引和短期状态。
- 本地 FastAPI 服务作为数据和任务的唯一事实来源。

不采用 Popup 作为主界面。Popup 在失去焦点后会关闭，不适合长耗时任务和长文本阅读。

### 4.2 前端技术栈

推荐：

- React。
- TypeScript。
- Vite。
- TanStack Query：请求状态、缓存和自适应轮询。
- Zustand：少量纯界面状态。
- `openapi-typescript`：根据 FastAPI OpenAPI 生成接口类型。
- Vitest：单元测试。
- Playwright：扩展端到端测试。

约束：

- 构建产物中的 JavaScript 必须全部随扩展打包。
- 不加载远程脚本。
- 不使用 `eval`。
- 不将 API 返回内容直接写入 `innerHTML`。

### 4.3 本地通信方式

第一版使用：

```text
Chrome Extension -> http://127.0.0.1:8000
```

后端只绑定环回地址：

```text
127.0.0.1
```

暂不使用 Native Messaging，原因是它需要：

- Windows 注册表或其他系统级 Host 注册。
- 独立安装器。
- Native Host 消息协议。
- 扩展 ID 和 Host 白名单维护。

当产品需要由扩展自动启动本地程序、完全隐藏 HTTP 端口或提供桌面安装包时，再评估 Native Messaging。

## 5. 总体架构

```text
┌──────────────────────────────────────────────────────────────┐
│ Chrome                                                       │
│                                                              │
│  当前标签页 / 分享文案                                       │
│            │                                                 │
│            ▼                                                 │
│  Side Panel                                                  │
│  - 采集表单              - 任务历史                           │
│  - 任务进度              - 结果查看                           │
│  - 复制/下载             - 导出状态                           │
│            │ runtime message                                 │
│            ▼                                                 │
│  Extension Service Worker                                    │
│  - 消息校验              - API Client                         │
│  - Token 管理            - 任务同步                           │
│  - chrome.alarms         - chrome.storage                     │
└────────────┬─────────────────────────────────────────────────┘
             │ HTTP / JSON / Bearer Token
             ▼
┌──────────────────────────────────────────────────────────────┐
│ FastAPI                                                      │
│  API 层 -> 持久化任务队列 -> 现有 Pipeline -> Result Service  │
│                              │                               │
│                              ├─ JSON / SRT / Markdown         │
│                              └─ Export Adapters               │
└────────────┬─────────────────────────────────────────────────┘
             ▼
      SQLite + data/tasks
```

## 6. 数据流

### 6.1 创建任务

1. 用户通过扩展图标或右键菜单触发采集。
2. Side Panel 获取当前标签页 URL，或接收用户粘贴的分享文案。
3. Side Panel 向 Service Worker 发送类型明确的消息。
4. Service Worker 校验输入、读取连接设置和 Token。
5. Service Worker 生成 `client_request_id`。
6. Service Worker 调用创建任务接口。
7. 后端以 `client_request_id` 做幂等检查。
8. 后端持久化任务后返回 `202` 和任务记录。
9. 扩展把任务 ID 写入本地任务索引。

### 6.2 任务同步

面板打开时：

- 运行任务以 1 秒、2 秒、5 秒的间隔自适应轮询。
- 任务进入终态后停止轮询。
- 页面重新打开时，根据本地任务 ID 从后端恢复状态。

面板关闭时：

- 使用 `chrome.alarms` 每 30 秒检查未完成任务。
- Service Worker 每次唤醒后重新从 `chrome.storage` 加载状态。
- 不依赖 Service Worker 全局变量保持任务状态。

任务终态：

- `completed`
- `failed`
- `cancelled`

### 6.3 结果读取

前端不直接组合多个产物文件来构建页面。后端提供统一的 Result DTO：

```json
{
  "schema_version": 1,
  "task_id": "uuid",
  "source": {
    "aweme_id": "...",
    "source_url": "...",
    "title": "...",
    "author": "...",
    "cover_url": "...",
    "duration_ms": 12345
  },
  "transcript": {
    "engine": "tingwu",
    "language": "zh",
    "text": "...",
    "segments": [
      {
        "start_ms": 0,
        "end_ms": 1500,
        "text": "..."
      }
    ]
  },
  "artifacts": [],
  "exports": []
}
```

产物接口继续用于文件下载，Result DTO 用于界面渲染。

### 6.4 导出

导出由后端执行，第三方凭据不进入扩展：

```text
ExportService
  ├─ MarkdownDownloadExporter
  ├─ ObsidianFolderExporter
  ├─ NotionExporter
  ├─ FeishuExporter
  └─ WebhookExporter
```

统一导出记录：

```json
{
  "id": "uuid",
  "task_id": "uuid",
  "destination": "notion",
  "status": "pending",
  "created_at": "...",
  "completed_at": null,
  "error": null,
  "external_url": null
}
```

## 7. Chrome 扩展设计

### 7.1 建议目录

```text
extension/
  manifest.json
  package.json
  tsconfig.json
  vite.config.ts
  public/
    icons/
  scripts/
    generate-api.ts
  src/
    background/
      service-worker.ts
      api-client.ts
      message-handler.ts
      task-sync.ts
    sidepanel/
      index.html
      main.tsx
      App.tsx
      pages/
        CapturePage.tsx
        TaskPage.tsx
        HistoryPage.tsx
        SettingsPage.tsx
      components/
        ConnectionStatus.tsx
        CaptureForm.tsx
        ProgressTimeline.tsx
        TranscriptViewer.tsx
        ArtifactList.tsx
        ErrorPanel.tsx
    shared/
      contracts/
        api.generated.ts
      messages.ts
      storage.ts
      task-status.ts
      validation.ts
    test/
```

### 7.2 Manifest 权限

最小权限建议：

```json
{
  "manifest_version": 3,
  "minimum_chrome_version": "120",
  "name": "Douyin Transcribe",
  "version": "0.1.0",
  "permissions": [
    "sidePanel",
    "storage",
    "activeTab",
    "contextMenus",
    "alarms"
  ],
  "host_permissions": [
    "http://127.0.0.1:8000/*"
  ],
  "background": {
    "service_worker": "service-worker.js",
    "type": "module"
  },
  "side_panel": {
    "default_path": "sidepanel.html"
  },
  "action": {
    "default_title": "打开抖音内容整理"
  }
}
```

第一版不申请：

- `<all_urls>`
- `history`
- `cookies`
- `webRequest`
- `scripting`
- `unlimitedStorage`

如果后续支持用户配置远程 API，将远程地址作为可选 Host Permission 动态申请，不预先申请全部 HTTPS 网站权限。

### 7.3 消息协议

Side Panel 不传递任意 URL 给 Service Worker 代为访问。消息使用封闭的判别联合：

```ts
type ExtensionRequest =
  | { type: "connection.check" }
  | { type: "tab.captureCurrent" }
  | { type: "task.create"; payload: CreateTaskInput }
  | { type: "task.get"; payload: { taskId: string } }
  | { type: "task.list"; payload: TaskListQuery }
  | { type: "task.retry"; payload: { taskId: string } }
  | { type: "task.cancel"; payload: { taskId: string } }
  | { type: "task.delete"; payload: { taskId: string } }
  | { type: "artifact.download"; payload: ArtifactDownloadInput };
```

Service Worker 必须：

- 按消息类型校验 payload。
- 校验 `sender.id`。
- 仅允许调用预定义 API 路径。
- 拒绝由页面控制的任意跨域代理请求。
- 返回统一错误结构。

### 7.4 本地存储

建议键空间：

```ts
interface ExtensionStorage {
  settings: {
    apiBaseUrl: string;
    preferredEngine: string;
    preferredFormats: string[];
  };
  auth: {
    token?: string;
  };
  tasks: {
    recentIds: string[];
    activeIds: string[];
  };
}
```

规则：

- 设置和最近任务存入 `chrome.storage.local`。
- 禁止将 Token 放入 `chrome.storage.sync`。
- 将 `storage.local` 的访问级别限制为可信扩展上下文。
- 大体积全文以服务端为准，不长期复制到扩展存储。
- 本地任务列表只是索引，不是事实来源。

### 7.5 页面结构

#### 采集页

- 当前页面 URL。
- 分享文案输入框。
- 转写引擎选择。
- 输出格式选择。
- 是否保留视频。
- 创建任务按钮。
- 后端连接状态。

#### 任务详情页

- 标题、作者和封面。
- 阶段时间线。
- 进度百分比。
- 错误信息和重试。
- 全文视图。
- 分段字幕视图。
- 产物下载。
- 复制纯文本和 Markdown。

#### 历史页

- 最近任务。
- 状态筛选。
- 标题搜索。
- 继续查看。
- 重试、删除。

#### 设置页

- API 地址。
- 配对 Token。
- 默认转写引擎。
- 默认输出格式。
- 连接测试。
- 清理本地索引。

## 8. 后端接口设计

### 8.1 能力发现

```http
GET /api/v1/capabilities
```

返回：

```json
{
  "api_version": "v1",
  "service_version": "0.2.0",
  "engines": {
    "whisper": true,
    "sensevoice": false,
    "tingwu": true,
    "openai": false
  },
  "formats": ["json", "srt", "markdown"],
  "exporters": ["download"],
  "limits": {
    "max_download_bytes": 524288000
  }
}
```

### 8.2 创建任务

保留现有接口：

```http
POST /api/v1/tasks/transcribe
```

扩展请求模型：

```json
{
  "input": "https://v.douyin.com/example/",
  "engine": "auto",
  "formats": ["json", "srt", "markdown"],
  "keep_video": false,
  "client_request_id": "uuid",
  "context": {
    "client": "chrome-extension",
    "client_version": "0.1.0",
    "page_url": "https://www.douyin.com/...",
    "page_title": "...",
    "captured_at": "2026-06-27T10:00:00Z"
  }
}
```

约束：

- 相同客户端和 `client_request_id` 返回原任务。
- `context` 只保存完成用户功能所需字段。
- 不保存浏览历史或无关页面内容。

### 8.3 任务列表

```http
GET /api/v1/tasks?status=completed&cursor=...&limit=20
```

响应：

```json
{
  "items": [],
  "next_cursor": null
}
```

使用游标分页，避免页码在新任务插入后产生重复或遗漏。

### 8.4 任务结果

```http
GET /api/v1/tasks/{task_id}/result
```

只有 `completed` 任务返回结果。其他状态返回明确的业务错误码。

建议支持：

- `ETag`
- `If-None-Match`
- `Cache-Control: private`

### 8.5 取消任务

```http
POST /api/v1/tasks/{task_id}/cancel
```

取消采用协作式取消：

- 队列中任务直接进入 `cancelled`。
- 执行中任务设置取消标志。
- Pipeline 在解析、下载、音频提取、转写和渲染阶段之间检查标志。
- 不承诺强制中止第三方已经创建的云端任务。

### 8.6 删除任务

```http
DELETE /api/v1/tasks/{task_id}
```

规则：

- 运行中任务不能直接删除，应先取消。
- 删除数据库记录和任务目录。
- 删除操作记录审计事件。
- 文件删除失败时返回可重试错误，不伪装成功。

### 8.7 导出

```http
POST /api/v1/tasks/{task_id}/exports
GET  /api/v1/tasks/{task_id}/exports
```

请求：

```json
{
  "destination": "notion",
  "options": {
    "database_id": "configured-alias"
  }
}
```

扩展只能传配置别名，不传第三方 Secret。

## 9. 错误模型

所有新接口返回统一错误结构：

```json
{
  "error": {
    "code": "SERVICE_UNAVAILABLE",
    "message": "Transcription service is not ready",
    "retryable": true,
    "details": {}
  }
}
```

首批错误码：

| 错误码 | HTTP 状态 | 是否可重试 |
| --- | --- | --- |
| `UNAUTHORIZED` | `401` | 否 |
| `TASK_NOT_FOUND` | `404` | 否 |
| `INVALID_INPUT` | `422` | 否 |
| `TASK_NOT_COMPLETED` | `409` | 是 |
| `TASK_ALREADY_RUNNING` | `409` | 否 |
| `ENGINE_UNAVAILABLE` | `503` | 是 |
| `SERVICE_UNAVAILABLE` | `503` | 是 |
| `RATE_LIMITED` | `429` | 是 |
| `EXPORT_FAILED` | `502` | 是 |

前端根据 `code` 决定交互，不解析英文错误字符串。

## 10. 持久化任务队列

### 10.1 选择

本地单用户版本使用 SQLite，不引入 Redis/Celery。

推荐数据表：

```text
tasks
  id
  client_request_id
  request_json
  status
  progress
  message
  error_code
  error_message
  cancel_requested
  created_at
  updated_at
  started_at
  completed_at

artifacts
  id
  task_id
  name
  media_type
  size
  relative_path
  created_at

exports
  id
  task_id
  destination
  status
  options_json
  error
  external_url
  created_at
  completed_at
```

### 10.2 Worker 模型

- FastAPI 启动时创建固定数量 Worker。
- 使用 `asyncio.Queue` 负责进程内调度。
- SQLite 保存任务真相。
- 默认转写并发数为 1，可配置。
- 启动时恢复 `pending`。
- 对原 `resolving` 至 `rendering` 状态任务执行恢复策略。

初始恢复策略建议：

```text
进程异常退出的非终态任务
  -> 标记 interrupted
  -> 自动重置为 pending
  -> 增加 attempt
  -> 超过最大次数后 failed
```

## 11. 鉴权与安全

### 11.1 配对 Token

本地服务首次启动时生成至少 256 bit 随机 Token，支持：

- 环境变量显式配置。
- 本地安全文件读取。
- 手动轮换。
- 扩展设置页粘贴配对。

请求头：

```http
Authorization: Bearer <token>
X-Client-Version: 0.1.0
```

除存活检查外，业务接口都要求鉴权。就绪接口是否公开由配置决定。

### 11.2 网络边界

- 默认只监听 `127.0.0.1`。
- 不默认监听局域网。
- 不启用 `Access-Control-Allow-Origin: *`。
- 如果增加普通 Web 前端，只允许明确配置的 Origin。
- 远程部署必须使用 HTTPS。

### 11.3 输入与输出安全

- 继续保留下载 URL 的 SSRF 防护。
- 所有任务 ID 使用 UUID 校验。
- 产物下载只能访问数据库登记的相对路径。
- 文件名使用允许列表。
- 前端使用 `textContent` 或 React 默认转义渲染文本。
- Markdown 预览若允许 HTML，必须先净化；第一版建议禁用原始 HTML。
- Content Script 消息一律视为不可信。

### 11.4 隐私

- 只在用户主动操作后采集当前 URL 或选中文本。
- 不收集完整浏览历史。
- 不上传与功能无关的数据。
- 发布商店前提供隐私政策和数据处理说明。
- UI 中明确展示数据发送到本地服务还是远程服务。

## 12. 实施拆解

### Phase 0：工程恢复与基线

目标：确保现有项目可以稳定开发和验证。

任务：

- 重建当前失效的 Python 虚拟环境。
- 安装开发依赖。
- 跑通全部现有测试。
- 确认 FFmpeg 探测。
- 修正文档显示编码问题。
- 记录当前 API OpenAPI 快照。

验收：

- `pytest` 全部通过。
- `ruff check .` 通过。
- `/health/live` 和 `/health/ready` 行为明确。
- Mock 引擎可以完成一次端到端任务。

### Phase 1：后端前端化接口

目标：提供扩展端可稳定消费的 API。

任务：

- 增加统一错误模型。
- 增加 `/api/v1/capabilities`。
- 增加任务列表和游标分页。
- 增加 `/result`。
- 增加 `client_request_id` 幂等创建。
- 增加任务取消。
- 增加任务删除。
- 扩充 API 测试。

验收：

- 重复创建请求不会产生重复任务。
- 扩展无需读取文件内容即可渲染完整结果。
- 任务列表可稳定分页。
- 错误响应包含稳定错误码。

### Phase 2：鉴权和持久化

目标：使本地 API 不被任意网页调用，并能恢复中断任务。

任务：

- 增加 Bearer Token 配置和中间件/依赖。
- 保留健康检查策略。
- 引入 SQLite Repository。
- 将任务和产物元数据迁移到 SQLite。
- 增加持久化 Worker 和并发限制。
- 增加启动恢复。
- 增加取消标志检查。
- 提供现有 `data/tasks` 的兼容或迁移脚本。

验收：

- 无 Token 不能创建或读取任务。
- 服务重启后任务记录仍存在。
- 重启后未完成任务按策略恢复。
- 同时创建多个任务不会无限并发执行。

### Phase 3：扩展工程骨架

目标：产出可在 `chrome://extensions` 加载的开发版。

任务：

- 创建 `extension/` 工程。
- 配置 React、TypeScript 和 Vite。
- 创建 Manifest V3。
- 创建 Service Worker。
- 创建 Side Panel。
- 配置图标和扩展 Action。
- 配置 `chrome.storage` schema。
- 配置 API 类型生成。
- 增加开发和生产构建脚本。

验收：

- `npm run build` 生成可加载目录。
- 点击扩展图标打开 Side Panel。
- 设置页可以保存 API 地址和 Token。
- 可以显示后端在线、未授权和离线三种状态。

### Phase 4：任务闭环

目标：完成从采集到结果查看的核心用户路径。

任务：

- 获取当前标签页 URL。
- 支持粘贴完整分享文案。
- 创建任务表单。
- Service Worker 消息协议和校验。
- API Client。
- 运行任务自适应轮询。
- 后台 Alarm 同步。
- 任务进度时间线。
- 失败重试。
- 最近任务列表。
- 完整结果和字幕分段视图。

验收：

- 从抖音页面最多三次操作即可创建任务。
- 关闭并重新打开 Side Panel 后任务仍可恢复。
- 后端重启期间显示可理解的离线状态。
- 任务成功后可看到全文和分段字幕。

### Phase 5：产物与导出

目标：完成整理后的数据交付。

任务：

- 复制纯文本。
- 复制 Markdown。
- 下载 JSON、SRT 和 Markdown。
- 增加导出接口和 Exporter 抽象。
- 首先实现 Download/Webhook Exporter。
- 后续按实际需求实现 Obsidian、Notion 或飞书。
- 保存导出记录和错误。

验收：

- 下载文件名、媒体类型和内容正确。
- 复制内容无 HTML 注入。
- 相同任务可以多次导出并分别看到状态。
- 第三方 Secret 不出现在扩展存储或日志中。

### Phase 6：测试、发布和运维

目标：达到可分发质量。

任务：

- 扩展单元测试。
- Service Worker 消息协议测试。
- Playwright 扩展端到端测试。
- 后端接口契约测试。
- 构建产物 CSP 检查。
- 权限审计。
- 隐私政策。
- Chrome Web Store 描述和截图。
- 版本兼容和升级说明。

验收：

- 核心端到端流程自动化通过。
- 扩展无远程托管代码。
- Manifest 不包含未使用权限。
- 发布材料准确描述数据用途。

## 13. 测试方案

### 13.1 后端

- 模型校验测试。
- 鉴权成功、失败和 Token 轮换测试。
- 幂等创建测试。
- 任务分页测试。
- Result DTO 测试。
- 重启恢复测试。
- 取消和删除竞态测试。
- 产物路径穿越测试。
- Exporter 超时和失败测试。

### 13.2 扩展

- API Client 请求和错误映射。
- 消息 payload 校验。
- Storage 迁移。
- 轮询退避。
- Service Worker 重启后的状态恢复。
- 任务状态到 UI 的映射。
- 复制和下载行为。

### 13.3 端到端

至少覆盖：

1. 后端在线且已配对。
2. 后端离线。
3. Token 错误。
4. 创建任务成功。
5. 任务执行失败并重试。
6. Side Panel 关闭后再打开。
7. Chrome 重启后恢复历史。
8. 下载三个标准产物。

## 14. 可观测性

后端日志至少包含：

- `request_id`
- `task_id`
- `client_request_id`
- `status`
- `engine`
- `duration_ms`
- `error_code`

不得记录：

- Bearer Token。
- 第三方 API Secret。
- 完整音频内容。
- 非必要的完整分享文案。

扩展端仅记录开发诊断信息，生产构建不输出 Token、完整结果或敏感请求头。

## 15. 版本与兼容策略

- API 路径保持 `/api/v1`。
- Result DTO 包含 `schema_version`。
- 扩展请求携带 `X-Client-Version`。
- `/capabilities` 返回后端版本和能力。
- 扩展启动时检查最低兼容 API 版本。
- Storage schema 包含版本号并提供迁移函数。

建议初始版本：

```text
Backend:   0.2.0
Extension: 0.1.0
API:       v1
Result:    schema_version 1
```

## 16. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 抖音页面或风控变化 | URL 解析失败 | 保留 Resolver 抽象、备用 API 和明确错误 |
| Service Worker 被回收 | 后台状态丢失 | 使用 `chrome.storage` 和 `chrome.alarms` |
| 后端进程退出 | 任务中断 | SQLite 队列和启动恢复 |
| 重复点击 | 重复消费资源 | `client_request_id` 幂等 |
| 本地端口被网页探测 | 未授权调用 | 环回绑定、Bearer Token、无通配 CORS |
| 转写耗时过长 | 用户误认为卡死 | 阶段进度、更新时间、取消和重试 |
| 远程代码违反商店政策 | 无法发布 | 所有前端代码本地打包 |
| 权限过宽 | 用户不信任或审核失败 | `activeTab` 和精确 Host Permission |
| 第三方凭据泄露 | 账号和数据风险 | 凭据仅由后端管理 |

## 17. 完成定义

第一版完成需要同时满足：

- Chrome 扩展可通过开发模式安装。
- Side Panel 可以采集当前 URL 和分享文案。
- 后端具备 Token 鉴权。
- 用户可以创建、查看、重试和取消任务。
- 服务重启后任务记录和历史不丢失。
- 完成任务可以展示结构化结果。
- JSON、SRT 和 Markdown 可以复制或下载。
- 扩展不申请无关权限。
- 核心后端和扩展流程有自动化测试。
- 安装、配对、启动和排错步骤有文档。

## 18. 推荐的首个开发迭代

为降低一次性改动风险，首个迭代只做以下内容：

1. 恢复 Python 开发环境和测试基线。
2. 增加 `capabilities`、任务列表和 `result` 接口。
3. 增加 `client_request_id`。
4. 创建最小 Chrome Side Panel 工程。
5. 接通连接测试、创建任务、状态轮询和结果展示。

首个迭代暂不迁移 SQLite、不做第三方导出。验证完整交互路径后，再进入鉴权与持久化改造。这样可以尽早暴露 API 契约和 UI 交互问题，同时避免在产品路径未验证前扩大基础设施改动。

## 19. 当前实施进度

截至 2026-06-27，首个开发迭代已经完成以下内容：

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| Python 开发环境 | 已完成 | 使用项目内 `.venv-dev` 恢复测试环境 |
| 现有测试基线 | 已完成 | 原有 21 个测试通过 |
| `capabilities` 接口 | 已完成 | 返回版本、引擎、格式、导出器和限制 |
| 任务列表接口 | 已完成 | 支持游标和 `limit` |
| 结构化 `result` 接口 | 已完成 | 返回来源、全文、分段和产物 |
| 幂等创建 | 已完成 | 支持 `client_request_id` |
| Chrome 扩展骨架 | 已完成 | Manifest V3、Side Panel、Service Worker |
| API 连接检查 | 已完成 | 区分在线和离线状态 |
| 当前标签页采集 | 已完成 | 使用 `activeTab`，未引入 Content Script |
| 创建和跟踪任务 | 已完成 | 面板轮询加后台 Alarm 同步 |
| 结果展示 | 已完成 | 展示全文、引擎和分段数量 |
| 最近任务 | 已完成 | 按视频聚合，展示最近 8 组任务和尝试次数 |
| 失败重试 | 已完成 | 展示后端错误并可重新执行 |
| 引擎可用性 | 已完成 | 根据 capabilities 禁用未配置引擎 |
| 产物下载 | 已完成 | 支持 JSON、SRT 和 Markdown 文本产物 |
| 后台同步容错 | 已完成 | 服务离线时保留待同步任务 ID |
| 扩展构建 | 已完成 | TypeScript 检查和 Vite 生产构建通过 |
| Bearer Token 后端鉴权 | 未开始 | 扩展设置页已预留 Token |
| SQLite 队列 | 未开始 | 下一阶段实施 |
| 取消、删除和导出 | 未开始 | 下一阶段实施 |

当前后端仍使用文件任务仓库和进程内 `asyncio` 任务。下一迭代应优先完成 Phase 2 的鉴权与持久化，之后再扩大外部导出能力。

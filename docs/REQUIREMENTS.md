# 抖音视频转录服务需求文档

> **范围说明**：本文是项目的**初始需求**，仅覆盖抖音转写。项目后续演进为 **MetaCorpus 元语助手**，新增了小红书抓取模块（`src/xhs_spider`）与 Chrome 扩展等能力，最新范围与用法以根目录 `README.md` 为准。

## 1. 项目目标

构建一个全 Python 的 FastAPI 服务，将抖音分享文案或链接转换为结构化视频信息、字幕和 Markdown 笔记。

系统默认完成免登录的单视频解析与转录。评论、作者主页和直播等需要登录态的深度采集能力作为可选适配器隔离，不进入默认链路。

参考项目及吸收方向：

- `vangie/douyin-transcriber`：轻量解析、下载、转录的完整链路。
- `chubbyguan/chubbyskills/douyin-transcribe`：Agent Skill 契约、分享页直解析、SenseVoice 本地转录。
- `cv-cat/DouYin_Spider`：评论、用户、直播等深度采集能力。

## 2. 核心原则

1. 全 Python 技术栈，业务逻辑与 HTTP 接口分离。
2. 默认链路免登录；Cookie 能力隔离、显式启用。
3. 解析器、转录器和渲染器均可插拔，并支持有序降级。
4. 长任务异步执行，请求立即返回任务 ID。
5. 原始数据、字幕和笔记均保留结构化产物。
6. 所有外部依赖可健康检查，失败可定位、可重试。

## 3. 用户场景

### 3.1 单视频转录

用户提交抖音链接或完整分享文案，服务解析视频、下载媒体、提取音频、转录并生成 JSON、SRT 和 Markdown。

### 3.2 查询任务进度

用户通过任务 ID 查询当前阶段、进度、错误信息和产物列表。

### 3.3 深度采集

用户显式要求评论或作者数据时，系统调用独立 Spider 适配器。默认关闭。

### 3.4 Agent 调用

Codex 等 Agent 通过 Skill 调用 HTTP API，轮询任务并读取最终 Markdown。

## 4. 功能需求

### P0：MVP

- 接收抖音链接或分享文案。
- 提取并跟随短链接。
- 解析分享页中的 `_ROUTER_DATA`。
- 下载视频并通过 FFmpeg 提取 16kHz 单声道 WAV。
- 支持 `mock`、OpenAI 兼容接口和 SenseVoice 转录器。
- 输出 `source.json`、`transcript.json`、`transcript.srt`、`notes.md`。
- 创建、查询、重试任务。
- 提供存活和就绪健康检查。
- 文件型持久化任务仓库，服务重启后可查询历史任务。

### P1：可靠异步执行

- 使用 Redis + ARQ 替代进程内任务队列。
- SSE 推送任务进度。
- 下载断点续传、任务取消、指数退避和并发限制。
- 解析响应样本与回归测试。

### P2：深度采集

- 将 DouYin_Spider 封装为独立服务。
- 评论、作者作品、直播数据接口。
- Cookie 密钥管理、限流、熔断与审计日志。

### P3：知识管理

- LLM 摘要和章节整理。
- 按字幕时间戳截图。
- qmd/Obsidian 索引与同步。
- Web 管理界面。

## 5. 非功能需求

- Python 3.11 及以上。
- API 使用 FastAPI 和 Pydantic。
- 网络请求使用 `httpx.AsyncClient`。
- 任务目录以 UUID 隔离，禁止用户输入直接参与文件路径。
- 日志不得记录 Cookie、Token 和完整授权头。
- 下载必须限制最大媒体体积。
- 下载器必须拒绝显式的本地和私有 IP 地址，降低 SSRF 风险。
- 生产环境必须配置 API Key 或网关鉴权。

## 6. API 契约

### 创建转录任务

`POST /api/v1/tasks/transcribe`

```json
{
  "input": "https://v.douyin.com/example/",
  "engine": "auto",
  "formats": ["json", "srt", "markdown"],
  "keep_video": false
}
```

### 查询任务

`GET /api/v1/tasks/{task_id}`

任务状态：

`pending -> resolving -> downloading -> extracting_audio -> transcribing -> rendering -> completed | failed`

### 查询产物

`GET /api/v1/tasks/{task_id}/artifacts`

### 下载产物

`GET /api/v1/tasks/{task_id}/artifacts/{name}`

### 重试任务

`POST /api/v1/tasks/{task_id}/retry`

### 健康检查

- `GET /health/live`
- `GET /health/ready`

## 7. 数据产物

```text
data/tasks/<task_id>/
  task.json
  source.json
  video.mp4
  audio.wav
  transcript.json
  transcript.srt
  notes.md
```

## 8. 模块拆解

```text
src/douyin/
  api/             FastAPI 路由
  resolvers/       分享页和备用解析器
  transcribers/    SenseVoice、OpenAI、Mock
  renderers/       JSON、SRT、Markdown
  services/        下载、FFmpeg、任务管线
  storage/         文件任务仓库
```

## 9. 验收标准

1. `POST /api/v1/tasks/transcribe` 在一秒内返回任务 ID。
2. Mock 转录模式无需模型即可完成端到端测试。
3. 失败任务记录明确阶段与错误消息，并可重试。
4. `/health/ready` 能识别 FFmpeg 和转录器配置状态。
5. 任务产物只能通过合法任务 ID 和白名单文件名访问。
6. 所有 P0 API 具有自动化测试。

## 10. 当前实现状态

- [x] M1：项目骨架、任务 API、文件仓库。
- [x] M2：分享页解析、备用解析 API、下载和 FFmpeg。
- [x] M3：Mock、SenseVoice、OpenAI 转录器与产物渲染。
- [x] M4：单元测试、Docker、基础 Skill。
- [ ] M5：Redis/ARQ、SSE 与 DouYin_Spider 深度采集服务。

## 11. 里程碑

1. M1：项目骨架、任务 API、文件仓库。
2. M2：分享页解析、下载和 FFmpeg。
3. M3：转录器路由与产物渲染。
4. M4：测试、容器化、Skill。
5. M5：Redis/ARQ 与深度采集服务。

# MetaCorpus 元语助手

MetaCorpus（元语助手）——抖音小红书元数据解析，AI 语料提取工具。一键解析短视频、笔记，提取文案字幕与完整元数据，输出结构化语料供给 AI 分析。

一个使用 Python 和 FastAPI 构建的后端服务：

- **抖音转写**：输入抖音分享链接或完整分享文案，解析视频、优先提取内嵌字幕，无字幕时调用本地模型、阿里听悟或 OpenAI-compatible API 完成语音转写。
- **小红书抓取**（`src/xhs_spider`）：登录后解析笔记/用户/搜索，提取完整元数据，支持媒体下载与 Excel 导出。

## 功能特性

- 支持抖音短链接、普通链接和完整分享文案。
- 直接解析抖音分享页，支持配置备用 Resolver API。
- 优先使用视频元数据中的字幕、ASR、OCR 或视频文本。
- 使用 FFmpeg 将视频转换为 16kHz 单声道 WAV。
- 支持阿里听悟、faster-whisper、SenseVoice 和 OpenAI-compatible API。
- 异步创建任务，支持状态查询、失败重试和产物下载。
- 输出视频元数据、结构化字幕、SRT 字幕和 Markdown 笔记。
- 下载大小限制、UUID 任务隔离和基础 SSRF 防护。

## 处理流程

```text
抖音分享文本或 URL
  -> 解析分享页或备用 Resolver API
  -> 获取视频信息和播放地址
  -> 检查内嵌字幕
     -> 有字幕：直接标准化
     -> 无字幕：下载视频 -> FFmpeg 提取音频 -> 调用转写引擎
  -> 生成 source.json / transcript.json / transcript.srt / notes.md
```

使用阿里听悟时，音频会先上传至 OSS，再创建听悟离线任务并轮询结果。完整技术说明见 [docs/DOUYIN_TINGWU_PIPELINE.md](docs/DOUYIN_TINGWU_PIPELINE.md)。

## 环境要求

- Windows、Linux 或 macOS
- 本地 Python 3.11 或更高版本
- FFmpeg，用于从视频中提取音频
- 真实转写所需的模型环境或第三方平台凭据

本项目默认使用本地 Python 虚拟环境，不要求 Docker。

## 本地安装

以下示例使用 Windows PowerShell：

```powershell
git clone https://github.com/izetaiota/meta.git
cd meta

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .

Copy-Item .env.example .env
```

安装完成后启动服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn douyin_transcribe.main:app `
  --host 127.0.0.1 `
  --port 8000
```

打开以下地址：

- Swagger API 文档：<http://127.0.0.1:8000/docs>
- 存活检查：<http://127.0.0.1:8000/health/live>
- 就绪检查：<http://127.0.0.1:8000/health/ready>

## FFmpeg

应用按以下顺序查找 FFmpeg：

1. 环境变量 `FFMPEG_PATH`。
2. 系统 `PATH` 中的 `ffmpeg`。
3. 项目目录 `.tools/ffmpeg/bin/ffmpeg.exe`。

`.tools/` 不会提交到 GitHub。若使用项目内 FFmpeg，请自行创建目录并放入可执行文件。

## 转写引擎

### Mock

Mock 用于无模型、无 API Key 的接口冒烟测试：

```env
TRANSCRIBE_ENGINE=mock
```

请求中必须显式指定 `"engine": "mock"`。`auto` 模式不会降级到 Mock，以免产生虚假的成功结果。

### 阿里听悟

```env
TRANSCRIBE_ENGINE=tingwu

ALIYUN_ACCESS_KEY_ID=your-access-key-id
ALIYUN_ACCESS_KEY_SECRET=your-access-key-secret
ALIYUN_OSS_BUCKET=your-bucket
ALIYUN_OSS_ENDPOINT=https://oss-cn-beijing.aliyuncs.com
ALIYUN_OSS_PREFIX=douyin-transcribe

TINGWU_APP_KEY=your-app-key
TINGWU_REGION=cn-beijing
TINGWU_LANGUAGE_HINT=cn
TINGWU_POLL_INTERVAL_SECONDS=5
TINGWU_TIMEOUT_SECONDS=1800
```

听悟流程：

1. 上传 `audio.wav` 到 OSS。
2. 生成临时签名 URL。
3. 创建听悟离线转写任务。
4. 轮询任务状态并下载结果 JSON。
5. 标准化时间轴并生成 JSON、SRT 和 Markdown。

请为 OSS 配置生命周期规则，避免转写音频长期保留。

### faster-whisper

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[whisper]"
```

CPU 示例：

```env
TRANSCRIBE_ENGINE=whisper
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
WHISPER_LANGUAGE=zh
```

GPU 示例：

```env
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
```

Windows 下可将 CUDA 运行库 DLL 放入 `.tools/cuda/bin`，应用会在启动本地模型前加载该目录。

### SenseVoice

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[sensevoice]"
```

```env
TRANSCRIBE_ENGINE=sensevoice
```

首次运行时，ModelScope/FunASR 会下载所需模型。

### OpenAI-compatible API

```env
TRANSCRIBE_ENGINE=openai
OPENAI_TRANSCRIBE_BASE_URL=https://api.openai.com/v1
OPENAI_TRANSCRIBE_API_KEY=your-api-key
OPENAI_TRANSCRIBE_MODEL=whisper-1
```

## API 使用

### 创建任务

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/tasks/transcribe `
  -H "Content-Type: application/json" `
  -d '{"input":"https://v.douyin.com/example/","engine":"tingwu","formats":["json","srt","markdown"],"keep_video":false}'
```

接口返回 HTTP `202` 和任务 ID。

### 查询任务

```powershell
curl.exe http://127.0.0.1:8000/api/v1/tasks/<task-id>
```

任务状态：

```text
pending
  -> resolving
  -> downloading
  -> extracting_audio
  -> transcribing
  -> rendering
  -> completed | failed
```

### 重试任务

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/tasks/<task-id>/retry
```

### 获取产物

```powershell
curl.exe http://127.0.0.1:8000/api/v1/tasks/<task-id>/artifacts
curl.exe -O http://127.0.0.1:8000/api/v1/tasks/<task-id>/artifacts/transcript.srt
```

## 产物目录

每个任务保存在独立目录：

```text
data/tasks/<task-id>/
  task.json
  source.json
  transcript.json
  transcript.srt
  notes.md
  video.mp4       # 仅 keep_video=true 时保留
```

| 文件 | 内容 |
| --- | --- |
| `task.json` | 请求、状态、进度、错误和产物列表 |
| `source.json` | 抖音视频信息和原始元数据 |
| `transcript.json` | 全文、引擎和分段时间轴 |
| `transcript.srt` | 标准 SRT 字幕 |
| `notes.md` | 带来源信息的 Markdown 笔记 |

## 开发与测试

安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

运行测试和静态检查：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

## 项目结构

```text
src/douyin_transcribe/
  api/             FastAPI 路由
  resolvers/       抖音分享页和备用 API 解析器
  services/        主流水线、媒体下载和内嵌字幕
  transcribers/    听悟、Whisper、SenseVoice、OpenAI 和 Mock
  renderers/       JSON、SRT 和 Markdown 渲染
  storage/         文件型任务仓库
src/xhs_spider/
  apis/            小红书 PC / Creator API 客户端（移植）
  xhs_utils/       签名运行时、JS 算法、数据处理（移植）
  spider/          批量抓取与下载编排（移植）
  integration/     异步 service、FastAPI 路由、登录驱动、任务仓库（新增集成层）
```

## 小红书（XHS）抓取模块

`src/xhs_spider/` 移植自 Spider_XHS，作为独立领域模块挂载到同一个 FastAPI 应用，复用其异步任务模型，路由前缀 `/api/v1/xhs`。

### 上游项目 / 维护说明

- **原始项目**：[cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS)
- `src/xhs_spider/{apis,xhs_utils,spider}` 是从上游**逐字移植**，仅重写了内部 import 前缀（`apis.` → `xhs_spider.apis.` 等），**未改动任何抓取/签名逻辑**。所有登录、签名 JS（`xhs_utils/*/js`）、数据解析均与上游一致。
- `src/xhs_spider/integration/` 是本项目**新增**的集成层（异步 service、FastAPI 路由、登录驱动、任务仓库），不属于上游。
- **升级方式**：从上游拉取新版后，覆盖 `apis/`、`xhs_utils/`、`spider/`，再对这三个目录批量执行 import 前缀重写（`from apis` → `from xhs_spider.apis`、`from xhs_utils` → `from xhs_spider.xhs_utils`、`from spider` → `from xhs_spider.spider`），`integration/` 一般无需改动。小红书线上算法变化时，通常只需同步上游的 `js/` 与 `apis/` 即可。

### 前置要求

- **Node.js**：签名运行时通过子进程调用 `node` 执行 `xhs_utils/*/js` 下的算法（`x-s`/`x-t`/`b1`/`websectiga`/`profileData`）。
- **crypto-js**：部分 JS 依赖该 npm 包，安装一次即可（Node 会从 js 目录逐级向上查找 `node_modules`）：

  ```powershell
  cd src\xhs_spider
  npm.cmd install
  ```

- **Python 可选依赖组**：

  ```powershell
  .\.venv\Scripts\python.exe -m pip install -e ".[xhs]"
  ```

### 登录

登录态按平台（`pc` / `creator`）留存于 `data/xhs/cookies.json`：

- Cookie 直登：`POST /api/v1/xhs/login/cookie`
- 扫码登录：`POST /api/v1/xhs/login/qrcode`（返回 base64 二维码）→ 轮询 `GET /api/v1/xhs/login/qrcode/{session_id}`
- 手机登录：`POST /api/v1/xhs/login/phone/code` → `POST /api/v1/xhs/login/phone/verify`
- 登录状态：`GET /api/v1/xhs/login/status?platform=pc`

> **扫码 / Cookie 登录均已实测可用。**
>
> - Cookie 直登：完整 Cookie 必须同时包含 HttpOnly 的 `web_session` 和前端 JS 写入的 `a1`。用浏览器 DevTools 复制请求头 Cookie，或使用配套扩展的「一键获取 Cookie 登录」（扩展会自动合并 `chrome.cookies` 与登录页 `document.cookie` 得到完整 Cookie）。
> - 扫码 / 手机登录：单个登录会话的 curl_cffi 请求必须固定在**同一线程**上完成整个流程（会话创建 → 轮询 → 换取正式会话）；跨线程复用会改变 libcurl 句柄的连接/TLS 状态，触发小红书风控软拒绝。服务端为每个登录会话分配独立单线程执行器来保证这一点。
>
> **验证结论（真实账号实测通过）**：扫码登录、Cookie 登录均可完成；`login/status` → `search`（关键词）→ `notes/detail` 全链路正常返回真实数据。

### 数据接口（直接返回 JSON）

笔记 / 搜索：

- 笔记详情：`POST /api/v1/xhs/notes/detail`
- 笔记评论：`POST /api/v1/xhs/notes/comments`
- 无水印视频 / 图片：`POST /api/v1/xhs/notes/no-water-video`、`POST /api/v1/xhs/notes/no-water-image`
- 关键词搜索笔记：`POST /api/v1/xhs/search`
- 搜索用户：`POST /api/v1/xhs/search/users`
- 搜索联想词：`POST /api/v1/xhs/search/keyword`
- 推荐流：`POST /api/v1/xhs/homefeed`、频道列表 `GET /api/v1/xhs/homefeed/channels`

用户：

- 用户资料：`POST /api/v1/xhs/users/info`
- 用户全部笔记 / 点赞 / 收藏：`POST /api/v1/xhs/users/notes`、`/users/like-notes`、`/users/collect-notes`

消息通知：`GET /api/v1/xhs/messages/{unread,mentions,likes-collects,connections}`

创作者中心：

- 已发布作品：`POST /api/v1/xhs/creator/posted-notes`
- 账号信息：`GET /api/v1/xhs/creator/user-info`
- 话题 / 位置搜索：`POST /api/v1/xhs/creator/topic`、`/creator/location`
- 发布链路：`POST /api/v1/xhs/creator/upload-media`、`/creator/post-note`（薄封装，尚未在真实账号验证）

蒲公英（品牌合作）：`POST /api/v1/xhs/pgy/{categories,users,user-detail}`

千帆（电商达人）：`POST /api/v1/xhs/qianfan/{categories,users,user-detail}`

> 蒲公英 / 千帆接口默认复用已登录的 PC Cookie，也可在请求体中单独传入 `cookies`。

### 异步下载/导出任务

`POST /api/v1/xhs/jobs` 创建抓取+下载任务（`type` 为 `notes`/`user`/`search`，`save_choice` 支持 `all`/`media`/`media-image`/`media-video`/`excel`）。通过 `GET /api/v1/xhs/jobs/{job_id}` 查询状态，产物（媒体、Excel）保存在 `data/xhs/jobs/<job_id>/`，可经 `GET /api/v1/xhs/jobs/{job_id}/artifacts/{path}` 下载。

## 当前限制

- 后台任务运行在当前 FastAPI 进程中，进程重启不会自动恢复未完成任务。
- XHS 登录会话（扫码/手机中间态）仅存于内存，进程重启后需重新发起登录。
- XHS 签名依赖外部 Node 与小红书线上算法，平台更新或风控变化可能导致失效。
- 暂未提供身份认证、限流、任务取消和 SSE 进度推送。
- 抖音分享页结构或风控变化可能导致直接解析失效。
- 发现内嵌字幕时会跳过下载和听悟，即使请求指定 `engine=tingwu`。
- 听悟上传到 OSS 的音频对象目前不会由应用主动删除。

生产部署前建议增加 API 鉴权、持久化任务队列、并发限制、结构化日志以及 OSS 生命周期策略。

## License

项目暂未附带开源许可证。公开分发或接受外部贡献前，请补充合适的 `LICENSE` 文件。

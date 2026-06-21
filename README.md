# Douyin Transcribe API

一个使用 Python 和 FastAPI 构建的抖音视频字幕提取服务。输入抖音分享链接或完整分享文案，服务会解析视频、优先提取内嵌字幕，并在没有字幕时调用本地模型、阿里听悟或 OpenAI-compatible API 完成语音转写。

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
```

## 当前限制

- 后台任务运行在当前 FastAPI 进程中，进程重启不会自动恢复未完成任务。
- 暂未提供身份认证、限流、任务取消和 SSE 进度推送。
- 抖音分享页结构或风控变化可能导致直接解析失效。
- 发现内嵌字幕时会跳过下载和听悟，即使请求指定 `engine=tingwu`。
- 听悟上传到 OSS 的音频对象目前不会由应用主动删除。

生产部署前建议增加 API 鉴权、持久化任务队列、并发限制、结构化日志以及 OSS 生命周期策略。

## License

项目暂未附带开源许可证。公开分发或接受外部贡献前，请补充合适的 `LICENSE` 文件。

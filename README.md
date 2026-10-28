# 心流 FlowPulse

> **繁杂交给系统，创作进入心流。**

**心流 FlowPulse** —— 面向个人博主、独立创作者的自媒体全域运营工作台。规划打通公众号 / 抖音 / 小红书 / 视频号，把选题库、素材库、多渠道消息聚合、批量分发、内容数据、投流 ROI 复盘收进一个系统，支持 SaaS 与 Docker 私有化本地部署。核心主张：不是帮你管控账号，而是砍掉运营琐事，保护你的创作状态。

- 官网：<https://izetaiota.github.io/FlowPulse/>
- 产品文档：[plan.md](plan.md)（命名方案、竞品调研、功能清单、官网文案、技术架构）
- 技术方案：[docs/](docs/) 目录（抖音转写流水线、公众号 RSS 迁移计划等）

## 项目状态

FlowPulse 处于 **早期开发阶段**，按「内容采集 → 工作台 → 分发与数据」的路径推进 MVP。当前已落地：

| 能力 | 目录 | 状态 | 说明 |
| --- | --- | --- | --- |
| 公众号订阅 RSS（微信读书通道） | `src/weread/` | ✅ 可用 | 订阅增删、增量同步、站内阅读、RSS 输出、内置定时调度、Webhook 告警 |
| 抖音转写 | `src/douyin/` | ✅ 可用 | 短视频解析 + 语音转写，输出结构化语料（JSON / SRT / Markdown） |
| 小红书抓取 | `src/xhs_spider/` | ✅ 可用 | 笔记 / 用户 / 搜索抓取、媒体下载、Excel 导出（真实账号实测通过） |
| 工作台前端 | `frontend/` | 🚧 骨架 | Vue3 + Element Plus；公众号订阅页已可用，其余页面为占位 |
| 官网落地页 | `website/` | ✅ 上线 | GitHub Pages 自动部署 |
| 消息中心 / 选题库 / 素材库 / 批量分发 / 内容与投流数据 | — | 📋 规划 | 见 [plan.md](plan.md) 功能需求清单 |

## 快速开始

### 后端

本地 Python 3.11+，无需 Docker：

```powershell
git clone https://github.com/izetaiota/FlowPulse.git
cd FlowPulse

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .

Copy-Item .env.example .env

.\.venv\Scripts\python.exe -m uvicorn metacorpus.main:app `
  --host 127.0.0.1 `
  --port 8000
```

打开以下地址：

- Swagger API 文档：<http://127.0.0.1:8000/docs>
- 存活检查：<http://127.0.0.1:8000/health/live>
- 就绪检查：<http://127.0.0.1:8000/health/ready>

### 工作台前端

```powershell
cd frontend
pnpm install
pnpm dev        # http://localhost:5173，/api 代理到 127.0.0.1:8000
```

页面模块（驾驶舱、账号管理、消息中心、选题、素材、公众号订阅、内容创作、发布任务、数据报表、设置）详见 [frontend/README.md](frontend/README.md)。

### Docker 部署（单容器，前后端合一）

```bash
docker compose up -d --build
```

打开 <http://127.0.0.1:8000> 即是工作台前端页面，`/api` 同源直达后端；运行时数据全部落在宿主机 `./data` 目录。

- 配置：把 `.env.example` 复制为 `.env` 放在项目根目录（转写引擎、微信读书 Cookie、Webhook 告警等），compose 会自动注入容器。
- 国内网络构建不畅时，可用 `--build-arg` 覆盖基础镜像与软件源（详见 `Dockerfile` 头部注释）：

  ```bash
  docker build \
    --build-arg NODE_IMAGE=docker.1ms.run/library/node:22-alpine \
    --build-arg PYTHON_IMAGE=docker.1ms.run/library/python:3.12-slim-bookworm \
    --build-arg APT_MIRROR=mirrors.tuna.tsinghua.edu.cn \
    --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    --build-arg NPM_REGISTRY=https://registry.npmmirror.com \
    -t flowpulse:latest .
  ```

- 镜像内置 FFmpeg（抖音音频提取）与 Node.js（小红书签名运行时）；因包含 opencv 等依赖，镜像体积约 1.5 GB。
- 扫码登录类功能（微信读书扫码续期、XHS 扫码登录）需要驱动本机可见浏览器，容器内不可用，请在容器内使用 Cookie 方式配置凭证。

## 公众号订阅 RSS（微信读书通道）

`src/weread/` 基于 [rachelos/we-mp-rss](https://github.com/rachelos/we-mp-rss)（MIT）的微信读书通道思路实现，是把公众号内容收进 FlowPulse 的第一步：**订阅公众号 → 定时增量同步 → 站内浏览 / RSS 输出**。

工作原理：

1. 在 **微信读书 App** 中订阅目标公众号（公众号在微信读书里表现为一种"书籍"，bookId 形如 `MP_WXS_3012726261`）；
2. FlowPulse 持有微信读书网页版 Cookie（关键键：`wr_vid`、`wr_skey`），轮询微信读书 Web API 拉取文章；
3. 从记录 ID 推导公众号原文链接（需将 token 中的 `~` 还原为 `_`，否则微信返回"参数错误"）；
4. 订阅关系由 FlowPulse 自行维护（新版微信读书书架接口不再返回公众号列表），添加订阅时粘贴微信读书链接或 bookId 即可。

### 使用流程

1. 浏览器登录微信读书网页版，复制 Cookie；
2. 保存凭证：`POST /api/weread/credential`（或 `.env` 中 `WEREAD_COOKIE`，服务启动时自动导入）；
3. 添加订阅：`POST /api/weread/subscriptions`，请求体 `{"input": "<微信读书链接或bookId>"}`，会自动反查公众号名称头像并入库最新一篇；
4. 手动全量同步：`POST /api/weread/sync`；此后由内置调度器定时增量同步；
5. 在 RSS 阅读器订阅输出，或在工作台前端 `/weread` 页面管理全部流程。

### API 一览

| 分组 | 接口 |
| --- | --- |
| 凭证 | `POST /api/weread/credential`（保存）、`GET`（查看脱敏状态）、`DELETE`、`POST /api/weread/credential/validate`（即时校验有效性） |
| 订阅 | `GET /api/weread/subscriptions`、`POST`（添加）、`DELETE /api/weread/subscriptions/{book_id}` |
| 文章 | `GET /api/weread/subscriptions/{book_id}/articles`（游标分页）、`GET /api/weread/articles/{book_id}/{review_id}/content`（站内阅读，正文按需抓取并缓存） |
| 同步 | `POST /api/weread/sync`（全部）、`POST /api/weread/subscriptions/{book_id}/sync`（单个）、`GET /api/weread/status`（凭证与各订阅健康状态） |
| RSS | `GET /api/weread/rss/all.xml`（全部订阅合并）、`GET /api/weread/rss/{book_id}.xml`（单个公众号） |
| 调度 | `GET /api/weread/scheduler`（状态）、`POST /api/weread/scheduler/trigger`（手动触发一轮） |

### 配置项

```env
WEREAD_COOKIE=                        # 启动时导入的微信读书 Cookie（可选，也可走 API）
WEREAD_REQUEST_INTERVAL_SECONDS=2.0   # 对微信读书接口的限速间隔
WEREAD_SYNC_INTERVAL_MINUTES=120      # 定时同步周期；<=0 关闭内置调度
WEREAD_WEBHOOK_URL=                   # 告警 Webhook（飞书/钉钉群机器人），Cookie 失效、同步失败时推送
WEREAD_RSS_FULL_TEXT=false            # RSS 是否输出全文（默认仅标题+链接+摘要）
```

数据保存在 `data/weread/`（订阅、文章、正文缓存、调度状态，文件型存储）。Cookie 有效期约数天到数周，过期时可通过 `status` 接口发现并触发 Webhook 告警，重新复制 Cookie 保存即可。

> 微信读书接口为非官方通道，本项目按"个人私有化使用 + 限速 + 过期告警"设计，请勿高频大量拉取。迁移决策与技术细节见 [docs/WECHAT_WEREAD_RSS_PLAN.md](docs/WECHAT_WEREAD_RSS_PLAN.md)。

## 抖音转写

输入抖音分享链接或完整分享文案，解析视频、优先提取内嵌字幕，无字幕时调用本地模型、阿里听悟或 OpenAI-compatible API 完成语音转写。

```text
抖音分享文本或 URL
  -> 解析分享页或备用 Resolver API
  -> 获取视频信息和播放地址
  -> 检查内嵌字幕
     -> 有字幕：直接标准化
     -> 无字幕：下载视频 -> FFmpeg 提取音频 -> 调用转写引擎
  -> 生成 source.json / transcript.json / transcript.srt / notes.md
```

- 支持短链接、普通链接和完整分享文案，可配置备用 Resolver API（`DOUYIN_RESOLVER_BASE_URL`）。
- 转写引擎：**阿里听悟**、**faster-whisper**（`pip install -e ".[whisper]"`）、**SenseVoice**（`pip install -e ".[sensevoice]"`）、**OpenAI-compatible API**、**Mock**（接口冒烟，仅显式指定时生效）。
- FFmpeg 查找顺序：环境变量 `FFMPEG_PATH` → 系统 `PATH` → 项目目录 `.tools/ffmpeg/bin/ffmpeg.exe`。
- 异步任务模型：`POST /api/v1/tasks/transcribe` 创建（202），`GET /api/v1/tasks/<task-id>` 查询，`POST .../retry` 重试，`GET .../artifacts` 获取产物。

产物目录：

```text
data/tasks/<task-id>/
  task.json          # 请求、状态、进度、错误和产物列表
  source.json        # 抖音视频信息和原始元数据
  transcript.json    # 全文、引擎和分段时间轴
  transcript.srt     # 标准 SRT 字幕
  notes.md           # 带来源信息的 Markdown 笔记
  video.mp4          # 仅 keep_video=true 时保留
```

各引擎的环境变量配置与听悟 OSS 流程说明见 [.env.example](.env.example) 和 [docs/DOUYIN_TINGWU_PIPELINE.md](docs/DOUYIN_TINGWU_PIPELINE.md)。

## 小红书抓取

`src/xhs_spider/` 移植自 [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS)（逐字移植，仅重写 import 前缀），挂载到同一个 FastAPI 应用，路由前缀 `/api/v1/xhs`。

- **前置**：Node.js（签名运行时）+ `cd src\xhs_spider && npm.cmd install`（crypto-js）；Python 依赖 `pip install -e ".[xhs]"`；可选代理 `XHS_PROXY`。
- **登录**：Cookie 直登 / 扫码 / 手机验证码，登录态留存于 `data/xhs/cookies.json`。扫码与 Cookie 登录均已真实账号实测通过；Cookie 直登需完整 Cookie（必须同时含 `web_session` 和 `a1`，可用仓库 `extension/` 下的配套 Chrome 扩展一键获取）。
- **数据接口**：笔记详情 / 评论 / 无水印媒体、关键词与用户搜索、推荐流、用户资料与笔记、消息通知、创作者中心、蒲公英 / 千帆，均直接返回 JSON。
- **异步任务**：`POST /api/v1/xhs/jobs` 创建抓取+下载任务（媒体、Excel 导出），产物在 `data/xhs/jobs/<job_id>/`。

上游同步与维护说明：平台算法变化时，从上游拉新版覆盖 `apis/`、`xhs_utils/`、`spider/` 三个目录并重写 import 前缀，`integration/` 集成层一般无需改动。

> ⚠️ 上游 [Spider_XHS](https://github.com/cv-cat/Spider_XHS) 仓库未附带开源许可证，其 README 声明「仅供学习交流使用，禁止任何商业化行为」；本模块请仅用于个人学习与研究，商用前请自行评估合规风险。

## 工作台前端

`frontend/` 为 Vue 3 + Vite + TypeScript + Element Plus + Pinia + Tailwind CSS 的管理后台骨架，页面模块按 [plan.md](plan.md)「产品功能需求清单」划分：

| 路由 | 模块 | 状态 |
| --- | --- | --- |
| `/weread` | 公众号订阅 | ✅ 已对接后端（Cookie、订阅、文章、RSS、定时同步） |
| `/dashboard`、`/accounts`、`/messages`、`/topics`、`/materials`、`/content/create`、`/publish`、`/reports/*`、`/settings` | 驾驶舱、账号、消息、选题、素材、创作、发布、数据、设置 | 🚧 骨架占位 |

详见 [frontend/README.md](frontend/README.md)。

## 项目结构

```text
src/
  metacorpus/        应用入口、全局配置（FastAPI app 工厂）
  weread/            公众号订阅 RSS（微信读书通道）：client / service / storage / rss / scheduler / notify / api
  douyin/            抖音转写：resolvers / services / transcribers / renderers / storage / api
  xhs_spider/        小红书抓取：apis / xhs_utils / spider（上游移植）+ integration（本项目集成层）
frontend/            Vue3 工作台前端
website/             官网落地页（GitHub Pages）
extension/           Chrome 扩展（小红书 Cookie 一键获取）
docs/                技术文档
scripts/             辅助脚本（微信读书通道 probe 等）
data/                运行时数据（任务、订阅、登录态，不入库）
```

## 开发与测试

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

## 路线图

- [x] 微信读书公众号订阅 RSS（订阅 / 增量同步 / RSS / 定时调度 / Webhook 告警）
- [ ] 工作台前端逐页落地（驾驶舱 → 消息中心 → 选题 / 素材库）
- [ ] 多平台账号接入与统一消息聚合
- [ ] 内容编辑与批量分发
- [ ] 内容数据监控与投流 ROI 分析
- [x] Docker 私有化部署（Dockerfile + docker-compose，单容器前后端合一）

完整功能需求清单见 [plan.md](plan.md)。

## 当前限制

- 后台任务与调度器运行在当前 FastAPI 进程中，进程重启不恢复未完成任务（调度状态已持久化，重启后继续）。
- 微信读书通道为非官方接口，存在频率限制与 Cookie 过期风险；高频大量拉取可能触发风控。
- XHS 签名依赖外部 Node 与小红书线上算法，平台更新或风控变化可能导致失效；XHS 登录中间态会话仅存于内存。
- 暂未提供身份认证、限流、任务取消和 SSE 进度推送。
- 抖音分享页结构或风控变化可能导致直接解析失效；发现内嵌字幕时会跳过下载和听悟转写。

生产部署前建议增加 API 鉴权、持久化任务队列、并发限制、结构化日志。

## License

[MIT](LICENSE) © 2026 izetaiota。其中 `src/xhs_spider/` 移植自 [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS)，`src/weread/` 采集思路参考 [rachelos/we-mp-rss](https://github.com/rachelos/we-mp-rss)（MIT，模块内已保留其版权声明）。

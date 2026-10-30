# 心流 FlowPulse

[English](./README.md) | 中文

> **繁杂交给系统，创作进入心流。**

## 一、项目简介

**心流 FlowPulse** —— 面向个人博主、独立创作者的自媒体运营工作台，支持 Docker 私有化部署与本地运行。核心主张：不是帮你管控账号，而是砍掉运营琐事，保护你的创作状态。账号凭证、订阅数据与媒体文件全部保存在本地，数据自留。

- 官网：<https://izetaiota.github.io/FlowPulse/>
- 产品与技术文档：[docs/](docs/) 目录（各模块实施计划、架构说明、迁移指南）
- 环境变量说明：[.env.example](.env.example)

**当前已落地的能力：**

| 能力 | 目录 | 状态 |
| --- | --- | --- |
| 公众号订阅 RSS（微信读书通道） | `src/flowpulse/modules/weread/` | ✅ 可用 |
| 抖音转写（解析 + 语音转写） | `src/flowpulse/modules/douyin/` | ✅ 可用 |
| 小红书工作台（抓取 / 下载 / 导出） | `src/flowpulse/modules/xhs/` | ✅ 可用 |
| 工作台前端（Vue3 + Element Plus） | `frontend/` | 🚧 持续完善 |
| 多平台账号中心 / 监控采集 / 发布 / 私信 | 规划中 | 📋 见 [迁移计划](docs/CREATORHUB_FEATURE_MIGRATION_PLAN.md) |

**快速开始：**

```bash
# Docker 一键部署（含 PostgreSQL）
docker compose up -d --build        # 打开 http://127.0.0.1:8000

# 或源码运行（Python 3.11+）
pip install -e . && cp .env.example .env
uvicorn flowpulse.main:app --host 127.0.0.1 --port 8000

# 前端开发模式
cd frontend && pnpm install && pnpm dev
```

架构要点：FastAPI 模块化单体（`modules/` 下按平台即插新模块）+ `runtime.py` 统一装配 + 文件 / PostgreSQL 双模式存储（`DATABASE_URL` 控制，Alembic 管理结构）+ 数据驱动菜单 + 单账号登录（HMAC Token）。详细部署、配置与 API 文档见 [docs/](docs/)。

## 二、特色功能亮点

### 📰 公众号订阅 RSS（微信读书通道）

- 应用内订阅公众号 → 定时增量同步 → 站内阅读 / RSS 输出（`/api/weread/rss/all.xml`，支持全文模式）
- **扫码登录 + Cookie 全自动续期与自愈**：无头浏览器每日续期，被其他设备轮换后自动刷新重试；登录态彻底失效时 Webhook 告警，扫码一次即恢复
- 订阅级独立同步周期、正文清洗定制（RSS 可配摘要/全文）、新文章多渠道通知推送
- 微信读书通道思路来自 [rachelos/we-mp-rss](https://github.com/rachelos/we-mp-rss)，实测稳定

### 🎬 抖音转写管线

- 粘贴分享文案即可：解析短链 → 优先提取内嵌字幕 → 缺失则下载视频、FFmpeg 提音频 → 语音转写
- **五引擎路由**：阿里听悟 / faster-whisper（本地）/ SenseVoice（本地）/ OpenAI 兼容 API / Mock，可按需安装与降级
- 结构化产物：`source.json` / `transcript.json` / `transcript.srt` / `notes.md`，异步任务模型（创建 202 + 轮询 + 重试）

### 🔴 小红书工作台

- **三路登录**：扫码 / 短信验证码 / 粘贴 Cookie（配套 Chrome 插件一键抓取），会话加密落盘、定时体检、掉线告警
- 数据接口：关键词搜索、笔记详情与评论、用户主页、无水印媒体下载、消息通知、创作者中心、蒲公英 / 千帆
- 异步抓取任务：批量采集 + 媒体下载 + Excel 导出，产物按任务目录归档

### ⚙️ 工程与部署

- **双模式存储**：默认零依赖文件存储（拷贝 `data/` 即完整备份）；设置 `DATABASE_URL` 切换 PostgreSQL，同一套仓储接口，附带一次性迁移脚本
- 凭证 Fernet 加密落盘；Webhook 通知渠道页面化管理（含发送记录环形日志）
- **控制台 CLI**：`python -m flowpulse.console weread-sync` 等一次性任务，输出 JSON、退出码可判，天然适配 cron / 计划任务
- Docker 单容器前后端合一（内置 FFmpeg 与 Node.js 签名运行时）；国内网络可用 build-arg 切换镜像源
- 测试覆盖后端各模块（pytest + respx），前端类型检查（vue-tsc）

## 三、引用资料、鸣谢与免责声明

### 引用与鸣谢

本项目在开发中参考、引用了以下项目与资料，向各位作者致谢：

| 项目 | 用途 | 协议 |
| --- | --- | --- |
| [rachelos/we-mp-rss](https://github.com/rachelos/we-mp-rss) | 公众号订阅的微信读书通道实现思路（`modules/weread/`） | MIT，版权声明保留于模块内 |
| [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS) | 小红书数据能力上游（`modules/xhs/` 原样移植，仅改 import 前缀，`integration/` 为本项目自研集成层） | 无开源协议，作者声明仅供学习交流、禁止商用 |
| [3441293738/creatorhub](https://github.com/3441293738/creatorhub) | 多平台内容管理（抖音/快手/视频号/TikTok）架构参考与功能沿用来源 | 无开源协议，见下方免责声明 |

主要依赖：FastAPI、SQLAlchemy / Alembic、Pydantic、Vue 3、Element Plus、Pinia、Playwright、curl_cffi、FunASR（SenseVoice）、faster-whisper、openpyxl、yt-dlp（规划中）。感谢这些优秀的开源项目。

### 免责声明

1. **本项目当前不附带任何开源协议**（All rights reserved © 2026 izetaiota），仅供作者个人本地使用，**请勿再分发或用于商业用途**。
2. 本项目依赖的能力（微信读书、抖音、小红书等）均为**非官方接口**，接口随时可能变更或失效，可能触发平台风控；使用产生的任何风险与后果由使用者自行承担。请低频、小量使用，遵守各平台服务条款，**严禁用于违规采集、数据倒卖或其他违法违规用途**。
3. 上游项目的权利归属各自作者：Spider_XHS 作者已声明"仅供个人学习交流，禁止商用"；本项目对 creatorhub 代码的沿用**未取得其作者授权**——若获取到本仓库副本，请勿公开传播，相关责任与本项目作者无关。
4. 所有凭证（Cookie 等）与数据仅存储于本地 `data/` 目录，请自行做好备份、加密与合规管理；因数据丢失或泄露造成的损失本项目不承担责任。
5. 本项目按"现状"提供，不作任何明示或默示的保证。

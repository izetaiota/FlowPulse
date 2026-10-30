#!/usr/bin/env bash
# 验证实例启动脚本：临时数据目录 + 全部调度器/自愈关闭 + 前端静态托管。
#
# ⚠️ 规约（docs/CREATORHUB_FEATURE_MIGRATION_PLAN.md §5）：
# 任何手工验证实例必须走本脚本（或显式导出下列全部变量），
# 禁止裸 uvicorn 指向真实 data/ —— 否则微信读书同步/续期、小红书凭证校验、
# 抖音/快手/TikTok 监控等调度器会以默认配置真实运行，反复请求平台页面。
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-8001}"
DATA_DIR="${DATA_DIR:-$(mktemp -d)/flowpulse_verify}"

export DATA_DIR
# ---- 关闭一切会外联/开浏览器的调度器与自愈 ----
export WEREAD_SYNC_INTERVAL_MINUTES=0        # 微信读书同步（含失效自愈→无头浏览器）
export WEREAD_COOKIE_REFRESH_HOURS=0         # 微信读书无头续期（开浏览器！）
export WEREAD_COOKIE=""                      # 不导入真实 Cookie
export XHS_CREDENTIAL_CHECK_MINUTES=0        # 小红书登录态校验
export XHS_MONITOR_ENABLED=false             # 小红书作品监控
export DOUYIN_MONITOR_ENABLED=false          # 抖音作品监控（开无头浏览器）
export DOUYIN_PUBLISH_ENABLED=false          # 抖音发布 worker（开有头浏览器）
export KS_MONITOR_ENABLED=false              # 快手作品监控（开无头浏览器）
export TIKTOK_MONITOR_ENABLED=false          # TikTok 关键词监控（外网直连）
export CHANNELS_BROWSER_HEADLESS=true
# 前端静态托管（Dockerfile 同款产物）
export STATIC_DIR="frontend/dist"

echo "[verify-instance] DATA_DIR=$DATA_DIR PORT=$PORT （全部调度器已关闭）"
PYTHONPATH=src python -m uvicorn flowpulse.main:app --host 127.0.0.1 --port "$PORT"

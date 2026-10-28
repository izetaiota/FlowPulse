# 基础镜像与软件源均可用 --build-arg 覆盖（默认为官方源，不影响常规构建）。
# 国内网络示例：
#   --build-arg NODE_IMAGE=docker.1ms.run/library/node:22-alpine
#   --build-arg PYTHON_IMAGE=docker.1ms.run/library/python:3.12-slim-bookworm
#   --build-arg APT_MIRROR=mirrors.tuna.tsinghua.edu.cn
#   --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
#   --build-arg NPM_REGISTRY=https://registry.npmmirror.com
ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG APT_MIRROR=""
ARG PIP_INDEX_URL=""
ARG NPM_REGISTRY=""

# ---------- 阶段 1：构建前端 ----------
FROM ${NODE_IMAGE} AS frontend-builder
ARG NPM_REGISTRY
ENV npm_config_registry=${NPM_REGISTRY}
WORKDIR /build
# 钉住 pnpm 版本：与本地/lockfile 一致（更新版本对构建脚本审批行为有变化）
RUN npm install -g pnpm@10.27.0
# 先装依赖再拷源码，充分利用层缓存
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# ---------- 阶段 2：运行时（后端 + 前端产物单容器） ----------
FROM ${PYTHON_IMAGE}
ARG APT_MIRROR
ARG PIP_INDEX_URL
ARG NPM_REGISTRY
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    DATA_DIR=/app/data \
    STATIC_DIR=/app/static
WORKDIR /app

# ffmpeg：抖音转写音频提取；nodejs：小红书签名运行时
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs npm tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
# xhs 可选组必装：应用启动时顶层即导入其模块（curl_cffi / loguru / cv2 等）
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install -i "$PIP_INDEX_URL" ".[xhs]"; \
    else \
        pip install ".[xhs]"; \
    fi

# 前端产物交给 FastAPI 同源伺服（页面与 /api 同一端口）
COPY --from=frontend-builder /build/dist/ ./static/

# 小红书签名 JS 依赖（crypto-js 等），装进 site-packages 内的包目录
RUN XHS_DIR="$(python -c 'import pathlib, xhs_spider; print(pathlib.Path(xhs_spider.__file__).parent)')" \
    && NPM_CONFIG_REGISTRY="$NPM_REGISTRY" npm install --prefix "$XHS_DIR" --no-fund --no-audit

VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "metacorpus.main:app", "--host", "0.0.0.0", "--port", "8000"]

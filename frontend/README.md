# 心流 FlowPulse 工作台前端

基于 **Vue 3 + Vite + TypeScript + Element Plus + Pinia + Tailwind CSS** 的管理后台骨架（技术栈对齐 [wa_cmf/frontend](https://github.com/izetaiota/wa_cmf/tree/main/frontend)），页面模块按 `plan.md`「产品功能需求清单」划分。

## 快速开始

```bash
pnpm install
pnpm dev        # http://localhost:5173，/api 代理到 127.0.0.1:8000
pnpm build      # 类型检查 + 生产构建（dist/）
pnpm typecheck  # 仅类型检查
pnpm preview    # 本地预览生产构建
```

## 页面模块（对应 plan.md）

| 路由 | 模块 | 说明 |
| ---- | ---- | ---- |
| `/dashboard` | 驾驶舱 | 总看板：消息 / 数据 / 投流汇总、快捷入口（当前为占位数据） |
| `/accounts` | 账号管理 | 四平台账号绑定与授权监控 |
| `/messages` | 消息中心 | 统一消息看板（核心差异化） |
| `/topics` | 选题管理 | 选题库 / 灵感库 / 排期日历 |
| `/materials` | 素材库 | 素材资产管理 |
| `/content/create` | 内容创作 | 统一编辑器 + 多平台分发配置 |
| `/publish` | 发布任务 | 发布队列、日志与失败重试 |
| `/reports/content` | 内容大盘 | 作品内容数据监控 |
| `/reports/ads` | 投流大盘 | 投流 ROI 分析（核心差异化） |
| `/settings` | 系统设置 | 私有化配置、Webhook、日志中心 |

## 目录结构

```
frontend/
├── src/
│   ├── api/client.ts          # axios 封装（拦截器占位）
│   ├── components/            # 通用组件（ModulePlaceholder 模块占位卡）
│   ├── layouts/DefaultLayout  # 侧栏 + 顶栏 + 内容区主布局
│   ├── router/                # 路由（与 plan.md 模块一一对应）
│   ├── stores/                # Pinia（侧栏状态持久化）
│   ├── styles/                # Tailwind + 品牌色 / Element 主色覆盖
│   └── views/                 # 10 个模块页面
└── vite.config.ts             # @ 别名、/api 代理、构建配置
```

## 约定

- 后端联调：本地启动 `uvicorn metacorpus.main:app --port 8000`，前端请求统一走 `/api` 前缀
- 品牌色：与官网一致（`--fp-primary: #6d5ef2`），在 `src/styles/index.css` 覆盖 Element Plus 主色
- V1 仅做单人使用，暂不引入登录与权限体系（后端接入后再补）

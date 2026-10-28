# Chrome 插件功能 Web 端移植实施计划（小红书工作台 + 转写任务中心）

> 目标：把 `extension/`（MetaCorpus 元语助手）承担的两块功能——**小红书 Cookie 一键采集**与
> **抖音/小红书解析任务侧边栏客户端**——移植到 Vue3 工作台 Web 端，交互与运维模式
> 对齐「公众号订阅」（weread）页：凭证卡片（扫码/粘贴/校验/告警）+ 功能卡 + 列表/抽屉。
> 移植完成后插件降级为可选的快捷入口，核心能力不再依赖它。

---

## 1. 现状调研（2026-10-28 实测盘点）

### 1.1 Chrome 插件（extension/，Manifest V3 侧边栏，React）

| 功能块 | 实现方式 | Web 端可替代性 |
| --- | --- | --- |
| 小红书 Cookie 一键获取 | 合并 `chrome.cookies.getAll`（HttpOnly `web_session`）+ 活动标签页 `document.cookie`（`a1/webId/gid`）→ `POST /api/v1/xhs/login/cookie` | ⚠️ 浏览器扩展权限才能读 HttpOnly 跨站 Cookie，**纯 Web 读不到**；替代路径=后端已有的扫码/验证码登录 |
| 抖音转写任务 | 侧边栏粘贴链接/取当前标签页 → `/api/v1/tasks/transcribe` → 轮询 → 结果/产物下载（JSON/SRT/MD） | ✅ 纯 API 调用，Web 天然可行 |
| 小红书抓取 | 侧边栏发起 search/notes/users 请求 → `/api/v1/xhs/*` | ✅ 同上 |
| 任务后台同步 | `chrome.alarms` 关闭侧边栏后继续轮询 | ✅ Web 端由后端任务状态承担，无需前端轮询保活 |

### 1.2 后端已有基建（`src/flowpulse/modules/xhs/integration/`，无需大改）

- **三路登录**：`POST /login/qrcode`（后端生成二维码 PNG base64）+ `GET /login/qrcode/{session_id}` 轮询；
  `POST /login/phone/code` / `/login/phone/verify`（短信验证码）；`POST /login/cookie`（粘贴）；
  `GET /login/status`（有效性）
- **抓取接口**：`/search`、`/notes/detail`、`/notes/comments`、`/users/notes`、`/users/info`、
  `/users/like|collect-notes`、`/creator/posted-notes`、`/jobs`（异步任务）
- **抖音转写**：`/api/v1/tasks/transcribe`（202 异步）+ 查询/重试/产物下载
- 登录会话由 `LoginDriver`（curl_cffi）在服务内存中维持 start→poll 状态机

### 1.3 差距清单

| 差距 | 说明 |
| --- | --- |
| 前端无任何 xhs / 转写页面 | 10 个骨架页中 `accounts` 为占位，插件侧边栏承担了全部 UI |
| 凭证无运维闭环 | 无定时校验、无失效 Webhook 告警（weread 已有同款，可平移） |
| Cookie 存储未加密 | weread 已做 Fernet，xhs store 未接 `core/storage` 加密 |
| 插件与服务端能力重复 | 插件是唯一 UI 的历史产物，Web 化后功能重叠 |

## 2. 技术方案

```
Web 工作台（Vue3）
├── /xhs        小红书工作台页（新）
│    ├─ 凭证卡片：扫码登录（展示后端二维码 PNG）/ 短信验证码 / 手动粘贴 Cookie
│    │           状态灯 + 重新校验 + 自动校验调度状态（对齐 weread 凭证卡交互）
│    └─ 抓取功能卡：搜索 / 笔记详情 / 用户笔记 / 评论，结果表格 + 详情抽屉
└── /transcribe 转写任务中心页（新，替代插件侧边栏）
     ├─ 提交卡片：粘贴抖音/小红书链接或完整分享文案（失去"当前标签页"能力，粘贴为主）
     └─ 任务列表：状态/进度/失败原因/重试 → 详情抽屉（转写全文 + JSON/SRT/MD 下载）

后端（基本复用，增量小）
├─ xhs integration API 原样复用
├─ 新增：XhsCredentialScheduler —— 定时校验 Cookie（复用 weread 调度器模式与 core/notify）
├─ 新增：xhs cookie 落盘接 core Fernet 加密（对齐 weread credential 方案）
└─ 插件 Cookie 通道保留为兜底（POST /login/cookie 不动）
```

## 3. 分阶段任务

### 阶段 0：可行性验证（Spike，半天）

- [ ] T0.1 起服务实测三路登录：扫码（PNG 展示→手机小红书 App 扫）、短信验证码、粘贴 Cookie
- [ ] T0.2 实测扫码/验证码登录后的抓取链路（search + notes/detail 各一次）
- [ ] T0.3 确认风控表现：curl_cffi 模拟登录的频控/验证码拦截情况，决定默认推荐登录方式

### 阶段 1：小红书工作台页（1~2 天）

- [ ] T1.1 前端 `/xhs` 路由 + 菜单「小红书工作台」；凭证卡片（扫码弹窗轮询 / 验证码两步表单 /
      粘贴对话框；状态灯映射对齐 weread）
- [ ] T1.2 抓取功能卡：搜索（关键词→笔记列表）、笔记详情、用户笔记；结果表格 + 点击抽屉看详情
- [ ] T1.3 异步 `/jobs` 轮询展示（搜索量大时后端走 job）
- [ ] 测试：前端 typecheck/build + 后端 respx 用例补 xhs 登录状态映射

### 阶段 2：转写任务中心页（1~2 天）

- [ ] T2.1 前端 `/transcribe` 路由 + 菜单；提交卡（分享文案/链接粘贴、引擎选择）
- [ ] T2.2 任务列表：进度/状态/失败原因/重试/按视频聚合（对齐插件侧边栏能力）
- [ ] T2.3 任务详情抽屉：转写全文复制 + JSON/SRT/Markdown 下载
- [ ] T2.4 骨架页 `publish`（发布任务）与本页关系处理：转写任务独立成页，`publish` 留给后续发布模块

### 阶段 3：运维闭环（对齐 weread，1 天）

- [ ] T3.1 `XhsCredentialScheduler`：定时校验（默认 6 小时）+ 失效 Webhook 告警（core/notify）
- [ ] T3.2 xhs Cookie 落盘 Fernet 加密（复用 `core/storage` + weread 密钥机制）
- [ ] T3.3 前端凭证卡接入校验调度状态展示（上次校验/下次校验）

### 阶段 4（可选）：插件定位调整

- [ ] T4.1 插件保留「当前标签页一键提交转写」「Cookie 兜底采集」两个轻功能，UI 类功能移除
- [ ] T4.2 或直接归档插件（README 标注由 Web 工作台替代）

## 4. 风险与边界

| 风险 | 应对 |
| --- | --- |
| 扫码/验证码模拟登录（curl_cffi）风控比微信读书严 | 阶段 0 实测定默认推荐路径；插件 Cookie 通道保留为兜底 |
| Web 端无法读 HttpOnly Cookie（插件的独有能力） | 已由后端扫码/验证码登录替代；插件保留兜底 |
| xhs 抓取接口为非官方通道 | 沿用模块内置代理/限速；个人私有化使用边界不变 |
| 短信验证码登录需要真实手机号 | 仅本人账号使用，不做多租户 |

## 5. 里程碑

1. **M1（阶段 0）**：三路登录 + 抓取链路实测通过
2. **M2（阶段 1~2）**：Web 端功能完整覆盖插件能力（产品闭环）
3. **M3（阶段 3）**：凭证运维闭环对齐 weread（定时校验/告警/加密）
4. **M4（阶段 4，可选）**：插件降级或归档

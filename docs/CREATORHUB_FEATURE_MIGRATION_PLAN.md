# CreatorHub 功能迁移实施计划

> 目标：把 [creatorhub](https://github.com/3441293738/creatorhub)（多平台内容管理工作台，支持抖音/小红书/快手/视频号/TikTok 的账号管理、采集监控、下载、发布、私信）的能力**分阶段移植进 FlowPulse**。
> 本地参考副本：`D:\www\www_py\creatorhub`（v0.2.6，后端约 4 万行）。
> 状态：计划阶段，未开工。

---

## 0. 结论先行

- **迁移方式（2026-10-30 已决策）：直接沿用 creatorhub 原有功能代码**，适配进 FlowPulse 的模块架构；为此 **FlowPulse 已去除 MIT 协议、改为无协议专有模式**（LICENSE 已删除）。风险与义务见 §1。
- creatorhub 的核心价值不在某个单一功能，而在四件资产：**① 平台×操作×通道（API/浏览器/混合）的能力矩阵与分流模式；② 多账号浏览器会话体系（Profile 隔离/指纹/代理/常驻复用）；③ 三套平台签名直连客户端（抖音 a_bogus、小红书 xhshow+Node、TikTok 纯离线）；④ 写操作风控闸**。迁移按这四条主线 + 功能切片推进。
- 建议节奏：先建基础设施（统一账号中心 + 浏览器会话层 + 通用任务引擎），再按"小红书 → 抖音 → 其余平台"逐平台补功能。FlowPulse 前端已预留 accounts/messages/materials/publish/reports 等占位页，正好逐一填坑。
- 预计总量：**6 个阶段、约 40+ 个任务**，P0–P1 完成后即可获得"多账号小红书监控采集"的可用闭环。

---

## 1. 协议与合规（2026-10-30 决策记录）

| 项 | 情况 |
|---|---|
| creatorhub | **无 LICENSE 文件、无任何协议声明** → 法律上默认"保留所有权利"，授权只能来自其作者 |
| FlowPulse | 原为 MIT 公开仓库；**本项目已按决策去除 MIT、删除 LICENSE，改为无协议专有模式**（README License 段、登录页脚已同步更新） |

**已执行的决策**：迁移直接沿用 creatorhub 功能代码。同时必须知悉并接受以下风险：

- 去掉 FlowPulse 自己的 MIT **并不能反向获得**复制 creatorhub 代码的授权——未经其作者许可的复制在法律上仍是侵权，这一点与本项目用什么协议无关。
- **仓库保持公开 = 分发行为，风险最高**。强烈建议：① 把 GitHub 仓库转为私有；② 有渠道时联系 creatorhub 作者取得书面授权。
- 个人本地使用、不分发的前提下实际风险相对可控，但性质不变，请自行权衡。
- 上游义务不因本项目改协议而消失：weread 模块沿用 rachelos/we-mp-rss（MIT，其版权声明须保留）；xhs 模块 vendored 自 cv-cat/Spider_XHS（无协议、仅供学习，README 已有警示）。
- 建议在直接沿用代码的模块内保留来源注释（`# ported from creatorhub`），便于后续溯源与替换。

---

## 2. 现状与差距矩阵

| 功能域 | creatorhub | FlowPulse 现状 | 差距 | 迁移价值 |
|---|---|---|---|---|
| 多平台账号中心 | 5 平台统一账号表、扫码/Cookie 登录、体检、重登 | 各模块独立凭证（weread/xhs 各一套） | 无统一账号层 | ★★★ 基础 |
| 浏览器自动化 | patchright + 系统Chrome CDP + 指纹/代理/Profile 隔离、常驻会话 | 仅 weread 扫码/xhs 走 vendored spider（无浏览器） | 无通用浏览器层 | ★★★ 基础 |
| 采集任务 | 关键词/创作者/收藏夹一次性批量采集 | xhs 已有 search/notes/users 快数据 + jobs 框架 | 缺监控型/批量型任务编排 | ★★★ |
| 作品/评论/弹幕监控 | 定时增量扫描、去重基线、回填 | 无 | 全缺 | ★★★ |
| 媒体下载 | 断点续传、画质选择、图集/视频 | xhs jobs 已有下载导出 | 部分有 | ★★ |
| 通用链接下载 | yt-dlp（抖音/B站/YouTube…） | 抖音分享解析仅服务转写 | 无通用下载 | ★★★ 低成本 |
| 发布 | 抖音/小红书/快手/视频号（浏览器自动化+API） | xhs creator 发布链已有 | 缺抖音/快手/视频号 | ★★ |
| 私信/自动回复 | 抖音 WS+protobuf、小红书页面观察 | 无 | 全缺 | ★★ 高成本 |
| 自动评论/账号动作 | 规则+审核流+写队列 | 无 | 全缺 | ★ |
| 风控中心 | 风险等级/冷却/配额/安静时段 | 无 | 全缺 | ★★（多账号后必要） |
| 通知 | Bark/钉钉/TG + Webhook outbox | Webhook 渠道 + 页面管理 ✅ | 缺 Bark/TG 渠道、webhook outbox | ★ 顺手补 |
| 报表导出 | 7 种 Excel | 无 | 全缺 | ★ 低成本 |
| 快手/视频号/TikTok | 各有采集/监控 | 无 | 全缺 | ★★ 后置 |
| 桌面端打包 | pywebview+PyInstaller+自动更新 | Docker/源码部署 | — | 不迁移（FlowPulse 定位 Web 自托管） |

---

## 3. 架构映射（creatorhub 概念 → FlowPulse 落点）

| creatorhub | FlowPulse 对应 | 说明 |
|---|---|---|
| `MonitorEngine` 巨型调度器 | lifespan 常驻调度器（weread_scheduler 模式）+ `runtime.py` 装配 + console `run_once()` | 不搬引擎类，按功能切片做**每域一个轻量调度器**，复用现有模式 |
| `transport_matrix`（平台×操作×通道分流） | `config.py` Settings 开关 + `/api/v1/capabilities` 报告 | 保留"能力矩阵 + 运行时 resolve"思想，实现为纯函数模块 `modules/platforms/transport.py` |
| `DouyinAccount` 多平台账号表 | 新表 `fp_accounts`（+ 凭证迁移），Alembic 0007 起 | 双模式仓储（PG/JSON），对接 `core/crypto.CredentialCipher`；多用户走已定稿的 RBAC 方案（0004 预留） |
| `BrowserManager`/`Identity`/Profile | 新模块 `modules/browser/`：patchright 可选依赖、Profile 目录隔离、登录驱动状态机 | 参照现有 `xhs/integration/login_drivers.py` 的 start→poll→verify 模式推广 |
| 平台签名客户端 | 每平台 `modules/<platform>/client.py`（**直接移植 creatorhub 代码 + 适配**，含签名 JS bundle） | xhs 侧优先沿用本项目已有 vendored spider；抖音 a_bogus/TikTok 离线签名等直接移植（来源注释） |
| 风控闸 `risk.py` | `modules/platforms/risk.py` + 账号表风控字段 | P4 再做，先在写操作里埋点 |
| 前端单页巨型 app.js | Vue3 工作台页面（凭证卡+Tabs+表格+抽屉模板） | 复用 weread/xhs 页面版式；占位页逐一替换 |

新模块一律遵循本项目已验证的移植套路（模块骨架/四件套/runtime 装配/双模式仓储/菜单注册/测试，见 xhs 与 weread 先例）。

---

## 4. 分阶段执行计划

### Phase 0 — 基础设施：统一账号中心 + 任务引擎（先行，其余都依赖它）✅ 2026-10-30 完成

- [x] T0.1 `fp_accounts` 表（迁移 0007）+ 双模式仓储（`modules/accounts/store.py`，PG / JSON 同构，凭证 Fernet 加密列与风控字段预留）
- [x] T0.2 账号中心 API（`/api/v1/accounts`：列表/平台元数据/managed CRUD/体检/删除）+ 前端 accounts 页（平台筛选、状态灯、体检、登记弹窗）
- [x] T0.3 weread/xhs 凭证收编：builtin 提供方协议（`BuiltinAccountProvider`）+ `WereadProvider`/`XhsProvider`，列表/体检/删除路由回所属模块（凭证仍由模块存储为单一事实源，账号表为统一视图与 managed 账号存储）
- [x] T0.4 统一任务视图：`/api/v1/queue`（聚合抖音转写 + 小红书抓取，按更新时间倒序，失败可重试）；前端「消息中心」页先承载任务动态（10s 轮询）
- [x] T0.5 `patchright` 可选依赖组 `browser` + `modules/browser/` 骨架（Profile uuid 分配不复用、上下文 LRU 回收、登录状态机 start→poll→verify，纯逻辑已测；浏览器驱动待 P3 落地）
- 验收：新增 managed 账号（API+页面实测）→ 列表可见 → 体检返回暂不支持提示；weread 写入凭证后 builtin 行自动出现并被清理跟踪；148 项测试全绿（新增 17 项）。

### Phase 1 — 小红书监控与批量采集（复用已有 spider，最快形成闭环）✅ 2026-10-30 完成（RSS 输出除外）

- [x] T1.1 `fp_xhs_monitors`（创作者/关键词双类型、目标级周期、包含/排除词、首扫基线条数，迁移 0008）+ 到期调度器（串行扫描 + 2 秒目标间隔，last_scan_at 持久化、重启补扫；对齐 weread 模式）
- [x] T1.2 增量扫描逻辑：首扫基线只入库不推送、note_id 全局去重、include/exclude 标题过滤；简化实现确定性到期（未做抖动散布，单实例低目标量下暂不需要）
- [x] T1.3 `fp_xhs_contents` 记录表 + 前端「作品监控」页（/xhs/monitor，目标管理/立即扫描/暂停恢复、作品分页表、来源筛选）+ 新作品汇总通知走现有 notify；菜单种子与前端兜底已加「作品监控」项（存量库需在设置页重置菜单或手插）
- [x] T1.4 批量采集：关键词/创作者批量 job、媒体下载与 Excel 导出**现有 jobs 框架已覆盖**（type=search/user/notes），无需扩展
- [ ] T1.5 新作品/评论监控 RSS 输出（通知推送已接；RSS 生成复用 weread 思路，暂缓）
- 补充：console 新增 `xhs-monitor-scan` 任务（到期目标扫描一次）；配置 `XHS_MONITOR_*`（开关/轮询/默认周期）
- 验收：创建关键词监控 → 后台调度自动到期扫描（未登录时优雅记录 error）→ 登录后即增量入库并推送通知；158 项测试全绿（新增 10 项），页面浏览器实测通过。

### Phase 2 — 通用链接下载 + 素材库（低成本高感知）✅ 2026-10-30 完成

- [x] T2.1 `yt-dlp` 可选依赖组 `download`（含 imageio-ffmpeg 兜底）+ `modules/downloader/`：分享文案抽链（多链去重）、任务化后台下载（进度写回 task.json）、失败重试、历史管理；ffmpeg 定位复用转写管线的 `find_ffmpeg`
- [x] T2.2 前端素材库页（materials 占位页替换）：链接下载卡片（粘贴文案→任务列表：进度/状态/重试/删除）+ 媒体库（downloads / xhs 双根目录浏览、面包屑导航、图片视频预览、删除；文件接口带目录穿越防护）
- [x] T2.3 与转写管线打通：抖音来源的已完成任务一键「转写」（原始链接提交转写管线）
- 验收：真实 yt-dlp 链路实测（创建→线程执行→失败记录→重试入队全通）；164 项测试全绿（新增 6 项）；素材库页浏览器实测通过。验收标准中的"粘贴真实抖音/B站文案下载"待有真实分享链接时人工确认。

### Phase 3 — 抖音平台（浏览器模式先行，API 签名后评估）✅ 2026-10-30 完成（T3.1–T3.5）

- [x] T3.1 抖音账号接入：`modules/douyin/account/`——粘贴 Cookie 导入（校验 sessionid+ttwid，Fernet 加密入 fp_accounts managed 行）+ 浏览器扫码登录（有头 Chrome，cookie 轮询→storage_state 入库，start→poll→verify 状态机带超时/取消）；账号中心自动出现抖音行
- [x] T3.2 浏览器拦截式读取：`modules/douyin/browser/`——patchright 优先/官方 playwright 回退（`modules/browser/engine.py`，系统 Chrome channel 免下载，ManagedContext 包装生命周期）；用户作品（/user/{sec_uid} 拦 aweme/post）与关键词搜索（拦 search/item）均滚动翻页采集
- [x] T3.3 抖音作品/评论监控：`fp_douyin_monitors/contents`（迁移 0009）+ 调度核心平台化（`modules/platforms/monitor_core.py`，xhs 调度器改为继承）+ 扫描语义与 xhs 一致（基线/去重/过滤/通知）；console 新增 `douyin-monitor-scan`；作品监控页平台化（平台筛选/抖音账号卡/创建对话框双平台/作品记录跨平台合并）
- [x] T3.4 抖音发布：`fp_douyin_publish_tasks`（迁移 0010）+ 发布驱动移植自 creatorhub publish.py（选择器多级兜底/风控人工验证窗口 5 分钟/诊断截图 data/debug/发布设置安全点选）+ 串行队列 worker（10s tick，有头执行）+ 前端「发布任务」页（媒体库选文件/草稿/立即发布/取消/删除，visibility 与保存权限）
- [x] T3.5 签名库移植：`modules/douyin/signing/`（a_bogus/sm3/rc4/ms_token/netfp，文件头均带来源声明）；性质测试通过（a_bogus 164 位/随机性/impersonate 映射）。**API 直连客户端集成留待需要时做**（当前浏览器模式已可用，签名库就位）
- 验收：180 项测试全绿（P3 共新增 16 项）；真实无头 Chrome 端到端实测监控扫描链路；发布驱动/队列以 mock 驱动测试 + 页面实测渲染（真实发布需用户扫码登录后人工确认，弹窗留有人工验证窗口）。

### Phase 4 — 私信与写操作风控（xhs 先、抖音后）✅ 2026-10-30 xhs 侧全部完成（T4.4 抖音私信除外）

- [x] T4.3 写操作风控闸：`modules/platforms/risk.py`（滚动小时窗口/日配额、失败冷却阶梯 30m→24h、跨午夜安静时段；状态落 data/risk/state.json）——已接入抖音发布队列与小红书私信发送：preflight 拦截保持原状态并写明原因，成功/失败回写计数与冷却
- [x] T4.1 小红书私信只读同步：`modules/xhs/dm/`（reader 移植 creatorhub xhs_im.py：/chat 页内第一方 fetch 观察会话与历史，免签名免二次 WS）+ API（conversations/messages）；消息中心页升级双 Tab（任务动态 | 私信），会话列表+未读徽标+消息抽屉
- [x] T4.2 自动回复规则与审核草稿 + **自动发送（2026-10-30 收尾）**：`fp_xhs_dm_rules/fp_xhs_dm_drafts`（迁移 0011 + 0013 加 error/sent_at 列）——未读消息按关键词规则生成 pending 草稿（去重）→ 页面通过/拒绝 → **「发送」按钮走浏览器 exactly-once 发送**（移植 xhs_dm.py 核心语义：气泡基线计数、dispatch 分界、写接口响应证据/气泡增量双重确认、write_uncertain 不重发），风控闸前置
- [ ] T4.4 抖音私信（frontier WS + protobuf 解析直接移植 creatorhub，共约 770 行；可降级为会话列表同步）
- 验收：200 项测试全绿（T4.2 发送闭环新增 4 项：payload 判定纯函数、mark_sent 状态流、风控拦截不消耗重试、FakePage 发送链路）；真实发送需用户登录小红书后人工确认。

### Phase 5 — 快手 / 视频号 / TikTok（独立增量，按需启动）🚧 T5.1 快手 + T5.4 报表完成

- [x] T5.1 快手（2026-10-30）：`modules/ks/`——extract 解析移植（多候选键兜底：REST /rest/v/profile/feed 与 GraphQL visionProfilePhotoList/VisionSearchPhoto 双通道）、拦截式 fetcher（profile/搜索页滚动拦截）、账号接入（Cookie 需 userId+passToken / 浏览器扫码状态机）、`fp_ks_monitors/contents`（迁移 0012）+ 通用调度；作品监控页第三平台化（快手账号卡/筛选/创建对话框）、console `ks-monitor-scan`、报表中心加快手两类
- [ ] T5.2 视频号：仅本账号作品/数据（创作者助手拦截，加密媒体只记元数据）
- [ ] T5.3 TikTok：**直接移植** creatorhub `platforms/tiktok/`（含 offline_sign 纯 Python 离线签名）+ 适配（2026-10-30 决策）；不做发布
- [x] T5.4 报表中心（2026-10-30）：`modules/reports/`——八类 xlsx 导出（xhs/douyin/ks 监控目标与作品、下载历史、账号清单，表头中文化、未装 openpyxl 优雅 400）；「数据报表→内容大盘」页替换为导出卡片（query token 直连下载）
- T5.1 验收：196 项测试全绿（新增 7 项）；真实 Chrome 验证三平台监控页与报表页；快手真实数据待用户登录后人工确认。
- 验收：每平台最小闭环（登录+采集列表+入库）。

### Phase 6 — 运营增强（可选）

- [ ] T6.1 Webhook 事件中心（outbox + HMAC 签名 + 重试，事件：新作品/风控/任务完成）
- [ ] T6.2 通知渠道补 Bark/Telegram（现有 notify 框架加渠道类型）
- [ ] T6.3 代理池管理（多账号隔离时才需要）
- [ ] T6.4 自动评论/账号动作（关注/取关）写队列——**暂不处理**（2026-10-30 决策，风控与合规敏感；后续要做得显式立项）

---

## 5. 依赖与工程配套（随阶段带入）

- `pyproject.toml` 新 optional 组：`browser`（patchright）、`download`（yt-dlp、imageio-ffmpeg）、`report`（openpyxl）
- Dockerfile：`browser` 组需要 Chromium 与中文字体（镜像显著变大，建议独立 `flowpulse-full` 变体或 compose profile）；`download` 组补 ffmpeg（已有）
- 数据约定：浏览器 Profile、媒体文件一律落 `data/`（PG 模式也只把元数据入库，二进制走文件系统），与现有 weread 文章缓存一致
- 测试：每模块 `tests/<module>/`，浏览器边界全部 mock（参考 creatorhub 的 no_real_browser 思路：未 mock 的浏览器调用 = 测试失败）；监控调度用假时钟测去重/回填
- 每阶段一个 PR 或一组小 PR，遵循现有提交风格（`feat:中文描述`）

---

## 6. 风险与决策点

**风险**
- R1 协议（§1）：已决策直接沿用代码 + 本项目改无协议模式；剩余动作=建议仓库转私有、争取原作者授权，并对沿用代码做来源标注。
- R2 平台风控时效：签名/接口随时失效；浏览器模式稳健但重。策略：抖音先纯浏览器（已决策），签名移植作为加速通道。
- R3 重量级浏览器栈与 FlowPulse 轻量部署冲突：patchright + Chromium 让镜像/内存翻倍。用 optional 组 + compose profile 隔离，核心功能不依赖浏览器。
- R4 双模式存储一致性：浏览器 Profile/媒体是文件资产，PG 模式下多实例部署会踩坑。约定单实例运行，文档写明。
- R5 抖音私信 WS/protobuf、TikTok 签名经"直接移植"决策后风险显著下降，但仍受上游代码质量与平台协议变化影响。

**决策点（2026-10-30 已全部拍板）**
- D1 浏览器内核：**patchright**，可配置回退官方 playwright。✅
- D2 抖音读取路线：**先纯浏览器拦截**，签名直连作为后续加速。✅
- D3 现有 weread/xhs 凭证：**收编统一账号列表**（见 T0.3）。✅
- D4 沿用方式/TikTok：**直接沿用 creatorhub 原有功能代码**（含 TikTok 模块整体移植），本项目去 MIT 改无协议模式（已执行）。✅
- D5 自动评论/关注类写操作：**暂不处理**（见 T6.4 标注）。✅

---

## 7. 工作量粗估（按阶段）

| 阶段 | 规模 | 说明 |
|---|---|---|
| P0 基础设施 | 中 | 表+仓储+浏览器骨架，约 8–10 个任务单元 |
| P1 小红书监控采集 | 中 | 复用 spider，主要是编排与前端 |
| P2 链接下载+素材库 | 小 | yt-dlp 封装为主 |
| P3 抖音 | 大 | 浏览器拦截+发布自动化 |
| P4 私信+风控 | 大 | 抖音私信最大风险点 |
| P5 其余平台 | 按平台增量 | 快手/视频号中等，TikTok 视决策 |
| P6 运营增强 | 小 | 独立可插 |

建议每阶段结束做一次回归（pytest 全绿 + 手工冒烟：登录→采集→下载→通知）。

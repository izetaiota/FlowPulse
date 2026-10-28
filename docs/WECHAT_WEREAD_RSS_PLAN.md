# 微信公众号订阅 RSS（微信读书通道）迁移实施计划

> 目标：将 [rachelos/we-mp-rss](https://github.com/rachelos/we-mp-rss) 的「微信读书采集公众号」能力迁移到 FlowPulse，
> 实现公众号订阅 → 定时同步文章 → 站内浏览 / RSS 输出。
> 范围限定：**只做微信读书（weread_mp）通道**。旧的「公众号平台 accessToken」方式已因微信收紧基本失效，不再实现。
> License 前提：we-mp-rss 为 MIT 协议，允许移植复用（需在模块内保留其版权声明）。

---

## 1. 调研结论

### 1.1 we-mp-rss 项目概况

| 项 | 结论 |
| --- | --- |
| 活跃度 | 5,042 stars / 841 forks，最近推送 2026-10-20（持续维护中） |
| 协议 | MIT（LICENSE 声明 Copyright (c) 2025 RACHEL） |
| 采集模式 | `web / api / app / free_publish / playwright / weread / weread_mp / auto`，本计划只用 **`weread_mp`** |
| 核心源码 | `core/wx/model/weread_mp.py`（公众号文章采集）、`core/wx/model/weread.py`（书架/笔记采集）、`core/weread_cookie_refresh.py`（Cookie 续期）、`jobs/mps.py`（定时调度） |

### 1.2 微信读书通道（weread_mp）工作原理（2026-10-27 实测更新）

1. 用户在 **微信读书**（App 为主）订阅公众号——公众号在微信读书里表现为一种"书籍"（bookId 形如 `MP_WXS_3012726261`）；
2. we-mp-rss / FlowPulse 持有用户微信读书 Cookie（关键：`wr_vid`、`wr_skey`），轮询微信读书 Web API 拉取文章；
3. 从记录 ID（形如 `MP_WXS_<bookId>_<articleToken>`）推导公众号原文链接 `https://mp.weixin.qq.com/s/<token>`；
   **关键坑**：微信读书把 token 里的 `_` 写成 `~`，必须还原，否则微信返回"参数错误"（issue #467）；
4. **实测关键事实**（2026-10-27，用真实 Cookie 全链路验证通过）：
   - ✅ `GET /api/mp/cover?bookId=` 可用：返回公众号最新一篇（标题/封面/reviewId/头像）；
   - ✅ `GET /web/mp/articles?bookId=&offset=` 在测试账号可用：一次返回约 20 篇（we-mp-rss 文档称新版已废弃恒 -2041，实测分账号，**必须保留 cover 兜底**）；
   - ⚠️ 新版微信读书**书架接口不再返回公众号**（`/web/shelf/sync` 的 books 里没有 `MP_WXS_` 条目），公众号订阅列表无法从服务端枚举 → **订阅关系由 FlowPulse 自己维护**，添加订阅靠「粘贴公众号链接/输入 bookId」；
   - ✅ reviewId → 原文短链推导 + `~`→`_` 还原实测正确，微信文章页可正常打开；
   - Cookie 存储于本地文件（如 `scripts/weread_cookie.txt`，已 gitignore），有效期待观察（社区经验数天~数周）。

### 1.3 已知风险信号（来自其 issues）

- **频率限制**：issue #469（2026-09-25）——`ret=200013` 频率限制，需要限速 + 触发后降级/退避；
- **Cookie 过期**：`-2012`（需续期）/ `-2010`、`-2041`（需重新扫码），we-mp-rss 的解法是"宿主机 Chrome + Playwright 每日打开微信读书页面提取新 Cookie 写回 wx.lic，容器只消费"；
- 结论：通道当前可用、社区修复响应快，但**本质是非官方接口**，必须按"个人私有化使用 + 限速 + 过期告警"设计。

### 1.4 备选项目对比（为何选 we-mp-rss 的微信读书通道）

| 项目 | 定位 | 与本需求关系 |
| --- | --- | --- |
| rokiai/lazy-ant-app | AI 内容创作 + 多平台**发布**桌面应用 | 发布侧工具，对应 FlowPulse「批量分发」模块的参考，与订阅采集无关 |
| k7airos/wx-publish-studio | 自托管公众号图文工作台，写文章 → 存草稿箱 | 同上，发布侧；明确"只写草稿箱，不群发" |
| kanadeblisst00/pywxrobot4 | 个人微信机器人（登录个人号收发消息） | 封号风险高，与 RSS 订阅采集目标不符 |
| rachelos/we-mp-rss | 公众号订阅 → RSS/Markdown/PDF，微信读书通道 | ✅ 唯一匹配，且活跃维护、MIT 可移植 |

---

## 2. 技术方案（FlowPulse 侧）

```
微信读书网页版（人工订阅公众号）
        │ Cookie（wr_vid / wr_skey）
        ▼
FlowPulse src/weread/ 模块（本计划新增）
  ├─ client.py      httpx 封装微信读书 Web API + 错误码映射 + 限速退避
  ├─ collector.py   同步流程：公众号列表 → 增量文章 → 入库
  ├─ models.py      MPAccount（订阅）/ MPArticle（文章）/ 凭证存储
  ├─ scheduler      定时任务（默认 2h，指数退避，参考 jobs/mps.py 的间隔控制）
  └─ api.py         REST + RSS 输出
        │
        ▼
FastAPI /api/weread/* ──► Vue3 前端「公众号订阅」页（复用 frontend/ 骨架）
```

- 技术栈与现有 `src/douyin` 模块保持一致（FastAPI + httpx + BeautifulSoup，httpx/bs4 已在依赖里）；
- 数据库沿用项目现有存储方案；
- ~~凭证加密存储对齐 plan.md「account_token 授权凭证加密表」设计~~ ✅ 2026-10-28 实现：
  Fernet 静态加密（密钥 `WEREAD_CREDENTIAL_KEY`，空则自动生成 `data/weread/.credential_key`），
  旧明文文件读取兼容、下次保存自动升级加密；未安装 cryptography 时降级明文（功能不受影响）。

---

## 3. 分阶段执行任务

### 阶段 0：可行性验证（Spike）✅ 2026-10-27 完成

- [x] **T0.1** 登录 weread.qq.com 获取 Cookie（已存 `scripts/weread_cookie.txt`，gitignore）
- [x] **T0.2** 一次性脚本 `scripts/weread_probe.py` 全链路验证通过：
  - 书架接口 OK（30 本）；确认新版书架不含公众号
  - `/api/mp/cover` OK（拉到最新一篇 + 头像/名称）
  - `/web/mp/articles` OK（一次 20 篇，含历史回补潜力）
  - reviewId → 原文链接（`~`→`_` 还原）推导正确，微信文章页实测可打开
  - 验证命令：`python scripts/weread_probe.py --book-id MP_WXS_xxxxxxx`

### 阶段 1：采集模块 + 凭证管理 ✅ 2026-10-27 完成

- [x] **T1.1** `src/weread/` 模块：`models.py`（MpSubscription/MpArticle/CredentialState）、
  `storage.py`（JSON 文件存储：credential.json / subscriptions.json / articles/<book_id>.json）
- [x] **T1.2** `client.py`：httpx 异步客户端，错误码映射（auth/rate_limit/api/network）、
  最小请求间隔限速（默认 2s + 抖动）、articles → cover 自动降级
- [x] **T1.3** `service.py`：增量同步（reviewId 去重、`~`→`_` token 还原）、
  凭证校验（书架受限时用订阅 cover 二次探测，识别半失效状态）
- [x] **T1.4** 凭证管理 API（`/api/weread/credential`、`/api/weread/status`），
  模块 docstring 保留 we-mp-rss MIT 来源声明
- [x] **T1.5** 订阅发现（`POST /api/weread/subscriptions`，支持 bookId 与链接两种输入，
  cover 反查名称头像并入库首篇文章）
- 测试：`tests/weread/test_weread.py` 10 个用例（respx mock），全仓 41 个测试通过；
  真实 Cookie 起服务完成 API 全流程联动验证（含真实降级：articles 接口 -2012 → cover 正常）


### 阶段 2：定时调度 + RSS 输出 + Webhook 告警 ✅ 2026-10-27 完成

- [x] **T2.1** 定时同步（`scheduler.py`：FastAPI lifespan 内置 asyncio 循环，
  `WEREAD_SYNC_INTERVAL_MINUTES` 默认 120 分钟、0=关闭；状态持久化 `data/weread/scheduler.json`；
  `GET /api/weread/scheduler` 查看状态，`POST /api/weread/scheduler/trigger` 手动触发）
- [x] **T2.2** RSS 输出（`rss.py` 手写 RSS 2.0 模板，无新依赖）：
  `GET /api/weread/rss/{book_id}.xml` 单订阅源 + `GET /api/weread/rss/all.xml` 合并源
- [x] **T2.3** Webhook 告警（`notify.py`：按 URL 自动适配飞书/钉钉/自定义格式，
  同类告警 1 小时冷却；Cookie 失效与同步异常两路告警，`WEREAD_WEBHOOK_URL` 配置）
- 测试：新增 8 个用例（RSS 格式与转义、三种 Webhook 载荷、冷却去重、调度触发告警），
  全仓 48 个测试通过；真实服务验证 RSS XML 输出、120 分钟调度循环与手动触发

### 阶段 3：前端页面 ✅ 2026-10-27 完成

- [x] **T3.1** `frontend` 新增「公众号订阅」页（`/weread` 路由，`views/weread/index.vue`）：
  - 凭证卡片：状态灯（有效/已失效/待校验/未配置）、粘贴/更新 Cookie 对话框、重新校验
  - RSS 卡片：合并源链接一键复制、定时同步状态（间隔/上次同步）、立即同步全部
  - 订阅列表：头像/名称/bookId/文章数/最近同步/状态标签 + 文章/同步/RSS/移除操作
  - 添加订阅：粘贴 bookId 或微信读书链接；文章预览抽屉（分页加载、点击跳原文）
- [x] **T3.2** 路由 + 侧栏菜单接入（菜单项「公众号订阅」）
- 验证：typecheck + build 通过；前后端联调实测（凭证校验 cover 兜底交互、订阅表真实数据、文章抽屉）

### 阶段 4（可选增强）：正文抓取与阅读 ✅ 2026-10-27 完成

- [x] **T4.1** 正文抓取（双路径：**公开原文页优先**——无需 Cookie、含完整富文本；
  微信读书 `/web/mp/content` 兜底——比 cover 更吃 Cookie，并修复其 HTTP 200 + JSON 错误体
  被误当 HTML 解析的坑）。提取支持 `#js_content` 节点与新版页面 `content_noencode` JS 变量
  双路径；**微信懒加载图片 `data-src` 回填 `src`**；图片统一加 `referrerpolicy=no-referrer`
  防盗链。存 HTML（保真优先，Markdown 转换后置），按 reviewId 文件缓存、抓一次不再请求。
  RSS 可选全文模式（`WEREAD_RSS_FULL_TEXT=true`，输出 content:encoded）。
- [x] **T4.2** 合规边界：仅个人订阅用途、走统一限速、不做转发分发
- 前端：文章抽屉升级为「列表/阅读」双视图——点击文章站内阅读富文本正文，
  顶部返回列表 + 微信原文入口，失败可重试
- 补充（2026-10-27 晚）：**发布时间回填**——cover 通道拿不到时间戳，抓公开原文页时
  顺带解析 `var ct`/`oriCreateTime`/`create_time` 标记，回填 `MpArticle.publish_time`
  （缓存缺时间会在下次阅读时补抓一次）；列表/阅读视图/RSS pubDate 均显示真实发布时间。
  前端文章列表加载失败时明确报错+重试，不再伪装成"暂无文章"。
- 验证：57 个测试全通过；真机实测正文 2.3 万字符、12/12 张图片全部加载成功，
  发布时间回填 2026/10/27 17:58:42 并在列表/RSS 生效

### 阶段 5（可选增强）：Cookie 自动续期 ✅ 2026-10-28 完成

- [x] **扫码登录**（T5.1 前半）：`src/weread/qrlogin.py` —— Playwright 弹本机
  Chrome（chrome→msedge→chromium 依次回退）打开 `weread.qq.com/#login`（登录页自动弹二维码），
  轮询浏览器 Cookie 拿到 `wr_vid/wr_skey` 后自动走 `save_credential` 校验入库；
  持久化 profile（`data/weread/browser_profile`）留存登录态，为自动续期铺路。
  API：`POST/GET/DELETE /api/weread/credential/qr-login`；前端「扫码登录」按钮 + 状态轮询弹窗。
  依赖 `pip install -e ".[weread]"`（playwright，用本机 Chrome 时无需下载浏览器）。
  真机已验证：用户扫码 → Cookie 自动捕获校验入库（书架 30 本，全量恢复）。
- [x] **T5.1 后半 · 每日自动续期**（2026-10-28）：`src/weread/refresh.py`
  `WereadCookieRefresher`——默认每 24 小时（`WEREAD_COOKIE_REFRESH_HOURS`，0 关闭）无头复用
  同一 profile 打开微信读书，服务端轮换 `wr_skey` 后提取最新 Cookie 写回并校验；
  与扫码窗口通过浏览器锁互斥（同 profile 不能双开）；profile 登录态也失效时标记凭证失效 +
  Webhook 告警提示重新扫码（重新扫码后 profile 恢复，续期继续生效）。
  API：`POST/GET /api/weread/credential/refresh`（手动触发/状态）；前端凭证卡「静默续期」按钮 +
  「Cookie 自动续期」状态行。真机验证：无头提取成功且 `changed=true`（wr_skey 确实被轮换），
  校验通过；68 个测试全通过。
- [x] **T5.2**：不做自动续期时的兜底（手动粘贴 + 过期告警）随 T5.1 一并具备；
  wr_skey 有效期由每日续期兜底（社区反馈数天~数周，续期后无需人工介入）。

---

## 4. 风险与合规

| 风险 | 应对 |
| --- | --- |
| 非官方接口，微信读书随时可能调整/风控 | 限速 + 退避 + 告警；采集层独立成模块，接口变了只改 client.py |
| Cookie 过期导致断更 | ✅ 已实现：扫码登录 + 每日无头自动续期（见阶段 5），登录态彻底失效时 Webhook 提醒重新扫码 |
| 频率限制 `200013` | ✅ 已实现：请求最小间隔限速（默认 2s + 抖动）+ 触发后 600 秒全局冷却（冷却期内直接拒绝请求不再打接口）；cover 模式下每订阅每轮仅 1 个请求，实际触发概率低 |
| 版权 | we-mp-rss 为 MIT，移植代码保留版权声明；文章内容仅个人阅读用途 |
| 账号安全 | 建议用小号绑定微信读书采集，避免主号 |

## 5. 里程碑建议

1. **M1（阶段 0）**：probe 脚本跑通 ← 先验证再投入
2. **M2（阶段 1~2）**：FlowPulse 内定时同步 + RSS 可订阅（后端闭环）
3. **M3（阶段 3）**：前端页面可用（产品闭环）
4. **M4（阶段 4~5，可选）**：正文阅读 + Cookie 自动续期

## 6. 参考资料

- we-mp-rss 关键源码：`core/wx/model/weread_mp.py`、`core/wx/model/weread.py`、`core/weread_cookie_refresh.py`、`jobs/mps.py`、`config.example.yaml`
- 其 issue #467（`~`→`_` token bug）、#469（频率限制降级）
- plan.md 模块 1（账号接入）、模块 9（自动化规则/Webhook）、参考资料清单

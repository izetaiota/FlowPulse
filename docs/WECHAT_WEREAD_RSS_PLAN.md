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
- 凭证加密存储对齐 plan.md「account_token 授权凭证加密表」设计。

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

### 阶段 1：采集模块 + 凭证管理（约 2~3 天）

- [ ] **T1.1** 新建 `src/weread/` 模块骨架与数据模型：
  - `mp_account`（订阅的公众号：bookId、名称、头像、最后同步时间、状态）
  - `mp_article`（文章：aid 唯一键、标题、链接、封面、摘要、发布时间、入库时间）
  - 凭证存储（wx.lic 或数据库加密字段，保存 wr_* Cookie + ticket + 更新时间）
- [ ] **T1.2** `client.py`：微信读书 Web API 封装
  - 错误码映射：`-2012`→Cookie 失效（触发告警）、`-2010/-2041`→需重新扫码、`200013`→频率限制（退避）
  - 请求间隔 ≥10s/篇、随机抖动、最多重试 2 次（对齐 we-mp-rss `interval` 默认值与 issue #469 教训）
- [ ] **T1.3** `collector.py`：增量同步（按 aid 去重、`~`→`_` token 还原、只拉新增）
- [ ] **T1.4** 凭证管理 API：
  - `POST /api/weread/credential`（手动粘贴浏览器 Cookie，V1 用这种）
  - `GET /api/weread/status`（Cookie 状态、各订阅最近同步结果）
  - 模块内保留 we-mp-rss 的 MIT 版权声明（NOTICE 注释）
- [ ] **T1.5** 订阅发现：新版书架不返回公众号，订阅关系由 FlowPulse 自维护——
  `POST /api/weread/subscriptions` 支持粘贴两种输入：`MP_WXS_xxx` bookId 或微信读书
  App「公众号主页 → 复制链接」得到的 `/web/mp/reader/MP_WXS_xxx` URL，后端调
  `/api/mp/cover` 反查公众号名称/头像后入库

### 阶段 2：定时调度 + RSS 输出（约 1~2 天）

- [ ] **T2.1** 定时同步任务（默认每 2 小时，可配置；复用 douyin 模块的调度模式）
- [ ] **T2.2** RSS 输出：`GET /api/weread/rss/{account_id}.xml` + 合并源 `/api/weread/rss/all.xml`（RSS 2.0，可先手写模板，不引重依赖）
- [ ] **T2.3** Cookie 过期 / 同步失败 Webhook 告警（对齐 plan.md 模块 9：推送到飞书/钉钉）

### 阶段 3：前端页面（约 1~2 天）

- [ ] **T3.1** `frontend` 新增「公众号订阅」页（替换现 `views/accounts` 里的占位或新增路由）：
  - 订阅列表（公众号名/头像/最近同步/文章数）、添加订阅（从微信读书书架选择）、移除
  - Cookie 设置入口 + 状态灯（有效/即将过期/已失效）
  - 文章列表预览（标题/时间/原文链接）
- [ ] **T3.2** 路由 + 侧栏菜单接入

### 阶段 4（可选增强）：正文抓取与阅读

- [ ] **T4.1** 抓取 `mp.weixin.qq.com/s/<token>` 正文存 Markdown（BeautifulSoup，参考 we-mp-rss `core/article_content.py` 与 `core/lax/template_parser.py` 思路）
- [ ] **T4.2** 合规边界：仅个人订阅用途、控制频率、不做转发分发

### 阶段 5（可选增强）：Cookie 自动续期

- [ ] **T5.1** 参考其 `core/weread_cookie_refresh.py`："宿主机本机 Chrome + Playwright 每日打开微信读书 reader 页 → 提取最新 Cookie → 写回"，FlowPulse 版本做成 `scripts/refresh_weread_cookie.py`
- [ ] **T5.2** 若不做自动续期，则依赖"手动粘贴 + 过期告警"，需在阶段 0 实测 wr_skey 实际有效期（社区反馈约数天~数周不等）

---

## 4. 风险与合规

| 风险 | 应对 |
| --- | --- |
| 非官方接口，微信读书随时可能调整/风控 | 限速 + 退避 + 告警；采集层独立成模块，接口变了只改 client.py |
| Cookie 过期导致断更 | 手动粘贴（V1）→ 自动续期脚本（V2），过期 Webhook 及时提醒 |
| 频率限制 `200013` | 单篇间隔 ≥10s、单次同步限量、触发后冷却 |
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

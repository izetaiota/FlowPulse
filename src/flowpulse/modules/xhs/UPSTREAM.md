# xhs_spider —— Vendored（内嵌第三方）说明

本目录中的抓取核心是从上游项目**移植（vendored）**而来，请按「上游镜像」对待。

## 上游

- 项目：**cv-cat/Spider_XHS**
- 地址：https://github.com/cv-cat/Spider_XHS
- 同步版本：`<在此填写同步时的 commit / 日期>`

## 目录边界

| 目录 | 归属 | 是否可改 |
| --- | --- | --- |
| `apis/` | 上游镜像 | ❌ 不要手改逻辑（仅 import 前缀改写） |
| `xhs_utils/`（含 `xhs_core`/`xhs_pc`/`xhs_creator` 与各 `js/`） | 上游镜像 | ❌ 同上 |
| `spider/` | 上游镜像 | ❌ 同上 |
| `integration/` | **本项目自研** | ✅ 集成层（service / 路由 / 登录驱动 / 任务仓库） |
| `package.json` / `node_modules` | Node 签名依赖（`crypto-js`） | 由 `npm install` 生成 |

上游镜像相对原仓库的**唯一改动**是内部 import 前缀：

- `from apis...` → `from xhs_spider.apis...`
- `from xhs_utils...` → `from xhs_spider.xhs_utils...`
- `from spider...` → `from xhs_spider.spider...`

> `xhs_core` / `xhs_pc` / `xhs_creator` 三套平行结构、以及重名的 `profile.js`、`reference_profile.json` 是上游针对不同平台（网页版 / 创作者中心）的签名变体，**并非冗余，请勿合并**。

## 升级步骤

1. 从上游拉取新版本，用其 `apis/`、`xhs_utils/`、`spider/` **覆盖**本目录对应内容。
2. 对这三个目录批量执行上面的 import 前缀改写。
3. 若上游新增了 npm 依赖，更新 `package.json` 后 `npm install`。
4. 跑集成层测试（`tests/test_xhs_*`）与冒烟登录验证。
5. 更新本文件顶部的「同步版本」。

`integration/` 一般无需随上游变动；小红书线上算法变化时，通常只需同步 `js/` 与 `apis/`。

# 官网 SEO 与搜索引擎收录指引

官网地址：<https://izetaiota.github.io/FlowPulse/>

## 已自动完成（无需操作）

| 项 | 说明 |
| --- | --- |
| 基础 meta | `title` / `description` / `robots: index,follow` / `canonical` / `theme-color` |
| Open Graph / Twitter Card | 分享到微信、Twitter、Slack 等平台时显示标题+描述+分享图（`og-image.png` 1200×630） |
| 结构化数据 | JSON-LD `SoftwareApplication`（搜索引擎结果富摘要） |
| `robots.txt` | 允许全部抓取，声明 sitemap 地址 |
| `sitemap.xml` | <https://izetaiota.github.io/FlowPulse/sitemap.xml> |
| IndexNow 自动推送 | 每次 GitHub Pages 部署后，Workflow 自动 POST `api.indexnow.org`，Bing / Yandex / Naver 等引擎会尽快来抓取（密钥文件 `website/<key>.txt` 随站部署） |

> 注意：Google 和百度都不支持 IndexNow，需按下面步骤手动提交一次，之后它们的爬虫会自行定期回访。

## 手动提交（各做一次即可）

### 1. Google Search Console

1. 打开 <https://search.google.com/search-console>，用 Google 账号登录；
2. 「添加资源」→ 选「网址前缀」→ 输入 `https://izetaiota.github.io/FlowPulse/`；
3. 验证方式选「HTML 标记」，复制给出的 `<meta name="google-site-verification" content="...">`；
4. 把这行 meta 加到 `website/index.html` 的 `<head>` 里（加在 `<!-- search-engine-verification -->` 注释处），提交推送，等 Actions 部署完成后回到 Search Console 点「验证」；
5. 验证通过后，在「站点地图」提交 `sitemap.xml`，并在「网址检查」里请求收录 `https://izetaiota.github.io/FlowPulse/`。

### 2. Bing Webmaster Tools（同时覆盖 Yahoo；也可从 GSC 一键导入）

1. 打开 <https://www.bing.com/webmasters>；
2. 可直接「从 Google Search Console 导入」，或手动添加站点后用同样的 HTML 标记方式验证；
3. 提交 sitemap。IndexNow 已自动化，Bing 收录通常较快。

### 3. 百度搜索资源平台（面向中文搜索，重点）

1. 打开 <https://ziyuan.baidu.com>，百度账号登录；
2. 「用户中心 → 站点管理 → 添加网站」，输入 `https://izetaiota.github.io`；
   ⚠️ 百度按域名（host）粒度管理，只能填 `https://izetaiota.github.io`，子路径 `/FlowPulse/` 无法单独添加；
3. 验证方式选「HTML 标记」，把 `<meta name="baidu-site-verification" content="...">` 同样加到 `website/index.html` 的 `<head>`，部署后完成验证；
4. 由于站点在子路径下，百度 sitemap 无法直接提交子路径 sitemap；替代方式：在「链接提交 → API 推送」用 curl 手动推一次首页 URL 即可，普通收录等待爬虫回访。

## 后续维护

- 每次官网内容有实质更新，无需额外操作：部署后 IndexNow 自动推送，Google/百度也会按自己的周期回访；
- 若新增独立页面（如功能介绍页），在 `website/sitemap.xml` 中补一条 `<url>`（`lastmod` 更新为当天）；
- 验证 meta 建议统一加在 `website/index.html` `<head>` 内 `<!-- search-engine-verification -->` 注释处，集中管理。

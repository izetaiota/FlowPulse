# Contributing Guidelines / 贡献约定

## README（双语两份，同步维护）

- `README.md` 为**英文版且是默认与基准版本**（GitHub 首先渲染），`README.zh.md` 为**中文版**。
- 两份文件顶部互有语言切换行：英文版 `English | [中文](./README.zh.md)`，中文版 `[English](./README.md) | 中文`。
- 结构固定三段（两份一致）：**① 项目简介；② 特色功能亮点；③ 引用资料、鸣谢与免责声明**。
- **任何文档改动必须同时改两份**、保持章节与表格一致：新增功能时更新「项目简介」能力表与「特色功能亮点」；引用了新上游项目时务必同步第三段的引用表与免责声明。
- 详细的部署 / 配置 / API 文档放 [docs/](docs/)，README 保持精简。

## Commit messages（中文）

- 统一使用 `<type>:<中文描述>`，类型取 `feat` / `fix` / `docs` / `refactor` / `test` / `chore`。
- 示例：`feat:统一品牌logo为公共组件AppLogoMark，登录页与侧栏同款`、`fix:订阅列表加载失败时明确报错并提供重试，不再静默空列表`。

## Code style

- Python: `ruff check` must pass (`line-length = 100`); tests via `pytest -q`.
- Frontend: `pnpm typecheck` in `frontend/`.
- 代码内注释、docstring 维持中文。

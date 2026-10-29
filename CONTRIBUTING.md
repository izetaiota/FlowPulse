# Contributing Guidelines / 贡献约定

## README (bilingual)

- `README.md` is the **English version and the default** (what GitHub renders first).
- `README.zh.md` is the **Chinese mirror**.
- Both files start with a language switch line — `English | [中文](./README.zh.md)` in the English file, `[English](./README.md) | 中文` in the Chinese one.
- **Keep the two files in sync**: any documentation change must be applied to both, with matching structure and section order. When adding a new section, add it to both files.

## Commit messages (English)

- Use English conventional commits: `<type>: <short imperative summary>` with types `feat` / `fix` / `docs` / `refactor` / `test` / `chore`.
- Examples: `feat: add weread RSS scheduler`, `fix: correct SPA fallback for api paths`, `docs: add English README`.
- Commits before October 2026 are in Chinese — leave history as is; new commits are English only.

## 中文说明（给中文协作者 / AI 助手）

- `README.md` 为英文版且是**默认与基准版本**，`README.zh.md` 为中文镜像；两份文件首行互链，**任何文档改动必须同时改两份**、保持章节一致。
- 自 2026 年 10 月起，**git 提交信息统一使用英文** conventional commits（`feat:` / `fix:` / `docs:` 等），不再使用中文描述；历史中文提交不回改。
- 代码内注释、docstring 维持现状（中文），除非另有说明。

## Code style

- Python: `ruff check` must pass (`line-length = 100`); tests via `pytest -q`.
- Frontend: `pnpm typecheck` in `frontend/`.

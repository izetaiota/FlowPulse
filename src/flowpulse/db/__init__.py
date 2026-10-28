"""FlowPulse 数据库层：SQLAlchemy 2.0 异步模型与引擎。

设计约定：
  - ORM 表按模块前缀命名（weread_*），后续模块各建各的表，共享同一个 Base
  - 所有时间列一律存 tz-aware UTC；DTO 层与既有 pydantic 模型互转
  - JSON 列用 sa.JSON（PG 上自动升为 JSONB），保证 sqlite 测试可跑
"""

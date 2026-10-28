"""把 data/weread/ 文件存储一次性迁移到 PostgreSQL。

用法（先建好表：DATABASE_URL=... python -m alembic upgrade head）：

    DATABASE_URL=postgresql+psycopg://flowpulse:flowpulse@127.0.0.1:5432/flowpulse \
        PYTHONPATH=src python scripts/migrate_weread_to_pg.py

幂等：全部走 upsert，重复执行不会产生重复数据。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from flowpulse.db.engine import create_engine_and_sessionmaker  # noqa: E402
from flowpulse.modules.weread.pg_repository import PgWereadRepository  # noqa: E402
from flowpulse.modules.weread.storage import WereadRepository  # noqa: E402

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))


def main() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("请设置 DATABASE_URL 指向 PostgreSQL")

    file_repo = WereadRepository(DATA_DIR)
    engine, sessionmaker_ = create_engine_and_sessionmaker(database_url)
    pg_repo = PgWereadRepository(
        sessionmaker_,
        key_file=DATA_DIR / "weread" / ".credential_key",  # 与文件版共用加密密钥
    )

    credential = file_repo.get_credential()
    if credential:
        # 保留原有校验状态（valid/last_validated_at/last_error）整体迁移
        pg_repo.update_credential(credential)
        print("凭证: 1（已迁移，含校验状态）")
    else:
        print("凭证: 0（文件存储无凭证，跳过）")

    subs = file_repo.list_subscriptions()
    total_articles = total_contents = 0
    for sub in subs:
        pg_repo.upsert_subscription(sub)
        articles = file_repo.list_articles(sub.book_id)
        total_articles += pg_repo.upsert_articles(sub.book_id, articles)
        count = 0
        for article in articles:
            content = file_repo.get_content(article.review_id)
            if content:
                pg_repo.save_content(content)
                count += 1
        total_contents += count
        print(f"订阅 {sub.name or sub.book_id}: 文章 {len(articles)} 篇 / 正文 {count} 篇")

    pg_repo.save_scheduler_state(file_repo.load_scheduler_state())
    pg_repo.save_cookie_refresher_state(file_repo.load_cookie_refresher_state())
    print(f"完成：订阅 {len(subs)}，新增文章 {total_articles}，正文缓存 {total_contents}，调度状态 2 项")
    engine.dispose()


if __name__ == "__main__":
    main()


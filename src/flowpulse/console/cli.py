"""console CLI 入口。

用法：
    python -m flowpulse.console list
    python -m flowpulse.console weread-sync
    python -m flowpulse.console weread-status

供 crontab / Windows 任务计划 / docker compose run 等外部调度定时调用；
任务定义与实现见 flowpulse.console.tasks。
"""

from __future__ import annotations

import argparse
import sys

from flowpulse.console import tasks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m flowpulse.console",
        description="心流 FlowPulse 一次性任务 CLI（跑完即退出，配合外部调度定时执行）",
    )
    sub = parser.add_subparsers(dest="task", required=True, metavar="task")
    sub.add_parser("list", help="列出全部可用任务")
    for spec in tasks.TASKS.values():
        sub.add_parser(spec.name, help=spec.help)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:  # argparse 参数错误：退出码交回调用方（测试/cron 可判定）
        return int(exc.code or 0)
    if args.task == "list":
        return tasks.list_tasks()
    return tasks.run_task(args.task)


if __name__ == "__main__":
    sys.exit(main())

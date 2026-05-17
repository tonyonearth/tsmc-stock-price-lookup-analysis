#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from datetime import datetime

import sys; sys.path.append(".")
from tsmc_agent_common import (
    build_line_push_text,
    find_latest_bundle,
    format_date,
    load_bundle_for_date,
    parse_date_arg,
    pretty_status_text,
    push_line_text_message,
    taipei_now,
    update_meta_flags,
)


def get_bundle(target_date: str | None, latest_available: bool):
    if latest_available:
        bundle = find_latest_bundle()
        if not bundle:
            raise SystemExit("找不到任何已建立的報告。")
        return bundle

    day = parse_date_arg(target_date)
    bundle = load_bundle_for_date(day)
    if not bundle:
        raise SystemExit(f"找不到 {format_date(day)} 的報告。")
    return bundle


def cmd_status(args: argparse.Namespace) -> int:
    bundle = get_bundle(args.date, args.latest_available)
    print(pretty_status_text(bundle))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    bundle = get_bundle(args.date, args.latest_available)
    summary_text = bundle["summary_text"].strip()
    if not summary_text:
        raise SystemExit("摘要檔存在，但內容為空。")
    if args.with_header:
        print(build_line_push_text(bundle["meta"], summary_text))
    else:
        print(summary_text)
    return 0


def cmd_report_path(args: argparse.Namespace) -> int:
    bundle = get_bundle(args.date, args.latest_available)
    print(bundle["paths"]["report"])
    return 0


def cmd_push_line(args: argparse.Namespace) -> int:
    bundle = get_bundle(args.date, args.latest_available)
    text = build_line_push_text(bundle["meta"], bundle["summary_text"])
    if args.dry_run:
        print(text)
        return 0

    responses = push_line_text_message(text)
    update_meta_flags(
        bundle["paths"]["meta"],
        line_push_attempted=True,
        line_push_sent=True,
        line_push_error="",
        line_push_response=responses,
        last_manual_line_push_at=taipei_now().isoformat(),
    )
    print("LINE 摘要已送出。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenClaw / 手動查詢用：讀取本機台積電報告狀態與摘要")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--date", help="報告日期，格式 YYYY-MM-DD；預設 today")
        p.add_argument("--latest-available", action="store_true", help="若指定，改抓最後一份可用報告")

    p_status = sub.add_parser("status", help="顯示報告狀態")
    add_common_flags(p_status)
    p_status.set_defaults(func=cmd_status)

    p_summary = sub.add_parser("summary", help="顯示 LINE 摘要")
    add_common_flags(p_summary)
    p_summary.add_argument("--with-header", action="store_true", help="加上可直接推送到 LINE 的標頭")
    p_summary.set_defaults(func=cmd_summary)

    p_report_path = sub.add_parser("report-path", help="輸出完整報告路徑")
    add_common_flags(p_report_path)
    p_report_path.set_defaults(func=cmd_report_path)

    p_push = sub.add_parser("push-line", help="手動重送 LINE 摘要")
    add_common_flags(p_push)
    p_push.add_argument("--dry-run", action="store_true", help="只顯示將要傳送的文字，不真的送出")
    p_push.set_defaults(func=cmd_push_line)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

TIMEZONE = ZoneInfo(os.getenv("REPORT_TIMEZONE", "Asia/Taipei"))
HTTP_TIMEOUT_SECONDS = int(os.getenv("HTTP_TIMEOUT_SECONDS", "30"))
USER_AGENT = "tsmc-personal-agent/2.0"
LINE_PUSH_API = "https://api.line.me/v2/bot/message/push"
SAFE_LINE_TEXT_CHUNK = 4000


def taipei_now() -> datetime:
    return datetime.now(TIMEZONE)


def format_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def parse_date_arg(raw: str | None) -> date:
    if not raw or raw.strip().lower() == "today":
        return taipei_now().date()
    return datetime.strptime(raw.strip(), "%Y-%m-%d").date()


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少必要環境變數：{name}")
    return value


def getenv_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _normalize_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _normalize_jsonable(asdict(value))
    if isinstance(value, dict):
        return {k: _normalize_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_normalize_jsonable(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_normalize_jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def get_report_bundle_paths(target_day: date) -> dict[str, Path]:
    stamp = format_date(target_day)
    return {
        "report": REPORTS_DIR / f"{stamp}_tsmc_report.txt",
        "summary": REPORTS_DIR / f"{stamp}_tsmc_summary.txt",
        "meta": REPORTS_DIR / f"{stamp}_tsmc_meta.json",
    }


def load_bundle_for_date(target_day: date) -> dict[str, Any] | None:
    paths = get_report_bundle_paths(target_day)
    if not paths["meta"].exists():
        return None
    bundle: dict[str, Any] = {
        "paths": paths,
        "meta": read_json(paths["meta"]),
        "report_text": read_text(paths["report"]) if paths["report"].exists() else "",
        "summary_text": read_text(paths["summary"]) if paths["summary"].exists() else "",
    }
    return bundle


def find_latest_bundle() -> dict[str, Any] | None:
    meta_files = sorted(REPORTS_DIR.glob("*_tsmc_meta.json"))
    if not meta_files:
        return None
    latest = meta_files[-1]
    target_day = datetime.strptime(latest.name[:10], "%Y-%m-%d").date()
    return load_bundle_for_date(target_day)


def _normalize_line_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text_for_line(text: str, chunk_size: int = SAFE_LINE_TEXT_CHUNK) -> list[str]:
    text = _normalize_line_text(text)
    if not text:
        return []

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        flush()
        if len(paragraph) <= chunk_size:
            current = paragraph
            continue

        # 單段仍太長時，改用硬切。
        for idx in range(0, len(paragraph), chunk_size):
            chunks.append(paragraph[idx : idx + chunk_size])

    flush()
    return chunks


def push_line_text_message(text: str) -> list[dict[str, Any]]:
    token = get_required_env("LINE_CHANNEL_ACCESS_TOKEN")
    target_id = get_required_env("LINE_TO_ID")

    chunks = chunk_text_for_line(text)
    if not chunks:
        raise RuntimeError("沒有可傳送到 LINE 的文字內容。")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }

    responses: list[dict[str, Any]] = []
    for start in range(0, len(chunks), 5):
        message_batch = chunks[start : start + 5]
        payload = {
            "to": target_id,
            "messages": [{"type": "text", "text": item} for item in message_batch],
        }
        resp = requests.post(
            LINE_PUSH_API,
            headers=headers,
            json=payload,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response_record = {
            "status_code": resp.status_code,
            "ok": resp.ok,
            "body": resp.text,
        }
        responses.append(response_record)
        resp.raise_for_status()
    return responses


def build_line_push_text(meta: dict[str, Any], summary_text: str) -> str:
    title = f"台積電({meta.get('stock_no', '2330')}) 每日摘要 {meta.get('report_date', '')}".strip()
    status_line = "今天已取得新的成交資料。" if meta.get("today_has_new_data") else "今天沒有新的成交資料。"
    lines = [
        title,
        f"最近成交日：{meta.get('latest_trade_date', '-')}",
        f"最近收盤價：{meta.get('latest_close', '-')}",
        f"最近漲跌價差：{meta.get('latest_change', '-')}",
        status_line,
        "",
        summary_text.strip() or "本日沒有可用摘要。",
    ]
    return "\n".join(lines).strip()


def update_meta_flags(
    meta_path: Path,
    **updates: Any,
) -> dict[str, Any]:
    payload = read_json(meta_path)
    payload.update(_normalize_jsonable(updates))
    write_json(meta_path, payload)
    return payload


def pretty_status_text(bundle: dict[str, Any]) -> str:
    meta = bundle["meta"]
    paths = bundle["paths"]
    lines = [
        "【台積電每日報告狀態】",
        f"報告日期：{meta.get('report_date', '-')}",
        f"建立時間：{meta.get('generated_at', '-')}",
        f"狀態：{meta.get('status', '-')}",
        f"最近成交日：{meta.get('latest_trade_date', '-')}",
        f"最近收盤價：{meta.get('latest_close', '-')}",
        f"最近漲跌價差：{meta.get('latest_change', '-')}",
        f"是否有今日新資料：{'是' if meta.get('today_has_new_data') else '否'}",
        f"Email 是否寄出：{'是' if meta.get('email_sent') else '否'}",
        f"LINE 是否送出：{'是' if meta.get('line_push_sent') else '否'}",
        f"本次 Gemini 模型：{meta.get('gemini_model_used') or meta.get('gemini_model') or '-'}",
        f"預設模型：{meta.get('gemini_model_primary', '-')}",
        f"備用模型：{meta.get('gemini_model_fallback', '-')}",
        f"主模型 thinkingBudget：{meta.get('gemini_thinking_budget_primary', '-')}",
        f"備用模型 thinkingBudget：{meta.get('gemini_thinking_budget_fallback', '-')}",
        f"本次實際 thinkingBudget：{meta.get('gemini_thinking_budget_used', '-')}",
        f"是否切換備用模型：{'是' if meta.get('gemini_fallback_used') else '否'}",
        f"完整報告：{paths['report']}",
        f"LINE 摘要：{paths['summary']}",
    ]
    if meta.get("market_event"):
        event = meta["market_event"]
        lines.append(
            f"官方開休市事件：{event.get('name', '')} {event.get('description', '')}".strip()
        )
    return "\n".join(lines).strip()

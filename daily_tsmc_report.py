#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import logging
import os
import re
import smtplib
import textwrap
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable

import requests
from google import genai
from google.genai import errors, types

import sys; sys.path.append(".")
from tsmc_agent_common import (
    BASE_DIR,
    DATA_DIR,
    REPORTS_DIR,
    build_line_push_text,
    format_date,
    get_report_bundle_paths,
    get_required_env,
    getenv_bool,
    push_line_text_message,
    taipei_now,
    update_meta_flags,
    write_json,
    write_text,
)

TIMEZONE = os.getenv("REPORT_TIMEZONE", "Asia/Taipei")
STOCK_NO = os.getenv("STOCK_NO", "2330")
PRIMARY_GEMINI_MODEL = os.getenv("GEMINI_MODEL_PRIMARY", "gemini-2.5-flash")
FALLBACK_GEMINI_MODEL = os.getenv("GEMINI_MODEL_FALLBACK", "gemini-2.5-flash-lite")
GEMINI_THINKING_BUDGET_PRIMARY = int(os.getenv("GEMINI_THINKING_BUDGET_PRIMARY", "-1")) # 0 ~ 24576 (0k ~ 24k)
GEMINI_THINKING_BUDGET_FALLBACK = int(os.getenv("GEMINI_THINKING_BUDGET_FALLBACK", "-1")) # 512 ~ 24576 (0.5k ~ 24k)
GEMINI_INCLUDE_THOUGHTS = getenv_bool("GEMINI_INCLUDE_THOUGHTS", False)
HTTP_TIMEOUT_SECONDS = int(os.getenv("HTTP_TIMEOUT_SECONDS", "30"))
USER_AGENT = "tsmc-personal-agent/2.0"

TWSE_HOLIDAY_API = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
TWSE_STOCK_DAY_API = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TWSE_STOCK_DAY_PAGE = "https://www.twse.com.tw/zh/trading/historical/stock-day.html"
DGPA_CALENDAR_PAGE = "https://www.dgpa.gov.tw/information?pid=12573&uid=41"

TSMC_HISTORY_PATH = DATA_DIR / "tsmc_history.csv"
LATEST_NEWS_CACHE_PATH = DATA_DIR / "latest_news_cache.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

LINE_SUMMARY_PATTERN = re.compile(
    r"<<<LINE_SUMMARY>>>\s*(.*?)\s*<<<END_LINE_SUMMARY>>>",
    flags=re.DOTALL | re.IGNORECASE,
)
CITATION_LABEL_RE = re.compile(r"\[\d+\]")
MAX_LINE_SUMMARY_LINES = 13



@dataclass
class HolidayEvent:
    event_date: date
    name: str
    weekday_zh: str
    description: str


@dataclass
class StockRow:
    trade_date: date
    volume_raw: str
    amount_raw: str
    open_raw: str
    high_raw: str
    low_raw: str
    close_raw: str
    change_raw: str
    trades_raw: str


@dataclass
class AnalysisResult:
    analysis_text: str
    summary_text: str
    grounding_sources: list[tuple[str, str]]
    primary_model: str
    fallback_model: str
    used_model: str
    fallback_used: bool
    fallback_reason: str
    attempted_models: list[str]
    primary_thinking_budget: int
    fallback_thinking_budget: int
    used_thinking_budget: int


def parse_recipients(raw: str) -> list[str]:
    parts =[p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


def to_gregorian_from_minguo_compact(raw: str) -> date:
    raw = raw.strip()
    if not re.fullmatch(r"\d{7}", raw):
        raise ValueError(f"無法解析民國日期：{raw}")
    year = int(raw[:3]) + 1911
    month = int(raw[3:5])
    day = int(raw[5:7])
    return date(year, month, day)


def to_gregorian_from_minguo_slash(raw: str) -> date:
    raw = raw.strip()
    m = re.fullmatch(r"(\d{2,3})/(\d{2})/(\d{2})", raw)
    if not m:
        raise ValueError(f"無法解析民國日期：{raw}")
    year = int(m.group(1)) + 1911
    month = int(m.group(2))
    day = int(m.group(3))
    return date(year, month, day)


def clean_numeric_text(raw: str) -> str:
    return raw.strip().replace(",", "")


def format_market_status(today_has_new_data: bool, market_should_open: bool, market_event: HolidayEvent | None) -> str:
    if today_has_new_data:
        return "今天已取得新的成交資料。"

    status_line = "今天沒有新的成交資料，可能是週末、國定假日、颱風停市，或 TWSE 尚未更新。"
    if market_event:
        extra = f"官方開休市事件：{market_event.name}"
        if market_event.description:
            extra += f"；{market_event.description}"
        return f"{status_line}\n{extra}"
    if not market_should_open:
        return f"{status_line}\n依開休市規則判斷，今天應屬非交易日。"
    return f"{status_line}\n依規則今天原則上應可交易，因此也可能只是 TWSE 尚未更新。"


def request_json(url: str, params: dict[str, Any] | None = None) -> Any:
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


def fetch_twse_holiday_events() -> list[HolidayEvent]:
    rows = request_json(TWSE_HOLIDAY_API)
    events: list[HolidayEvent] =[]
    for row in rows:
        try:
            events.append(
                HolidayEvent(
                    event_date=to_gregorian_from_minguo_compact(str(row["Date"])),
                    name=str(row.get("Name", "")).strip(),
                    weekday_zh=str(row.get("Weekday", "")).strip(),
                    description=str(row.get("Description", "")).strip(),
                )
            )
        except Exception as exc:
            logging.warning("略過無法解析的 holiday row: %s | error=%s", row, exc)
    return events


def get_market_open_status(target_day: date, events: Iterable[HolidayEvent]) -> tuple[bool, HolidayEvent | None]:
    matching = [e for e in events if e.event_date == target_day]
    if matching:
        event = matching[0]
        text = f"{event.name} {event.description}"
        if ("開始交易" in text) or ("最後交易日" in text):
            return True, event
        return False, event

    if target_day.weekday() >= 5:
        return False, None

    return True, None


def fetch_monthly_stock_rows(stock_no: str, year: int, month: int) -> tuple[list[StockRow], dict[str, Any]]:
    payload = request_json(
        TWSE_STOCK_DAY_API,
        params={
            "response": "json",
            "date": f"{year}{month:02d}01",
            "stockNo": stock_no,
        },
    )

    data_rows = payload.get("data") or []
    rows: list[StockRow] =[]

    for row in data_rows:
        if len(row) < 9:
            continue
        try:
            rows.append(
                StockRow(
                    trade_date=to_gregorian_from_minguo_slash(str(row[0])),
                    volume_raw=str(row[1]),
                    amount_raw=str(row[2]),
                    open_raw=str(row[3]),
                    high_raw=str(row[4]),
                    low_raw=str(row[5]),
                    close_raw=str(row[6]),
                    change_raw=str(row[7]),
                    trades_raw=str(row[8]),
                )
            )
        except Exception as exc:
            logging.warning("略過無法解析的 stock row: %s | error=%s", row, exc)

    rows.sort(key=lambda x: x.trade_date)
    return rows, payload


def collect_recent_stock_rows(stock_no: str, today: date, lookback_months: int = 3) -> list[StockRow]:
    months: list[tuple[int, int]] =[]
    cursor = today.replace(day=1)
    for _ in range(lookback_months):
        months.append((cursor.year, cursor.month))
        cursor = (cursor - timedelta(days=1)).replace(day=1)

    merged: dict[date, StockRow] = {}
    for year, month in months:
        rows, _ = fetch_monthly_stock_rows(stock_no, year, month)
        for row in rows:
            if row.trade_date <= today:
                merged[row.trade_date] = row

    return sorted(merged.values(), key=lambda x: x.trade_date)


def pick_latest_row(rows: list[StockRow], today: date) -> tuple[StockRow, bool]:
    eligible = [r for r in rows if r.trade_date <= today]
    if not eligible:
        raise RuntimeError("找不到任何可用的台積電成交資料。")
    latest = eligible[-1]
    return latest, latest.trade_date == today


def _segment_overlaps_ranges(start_index: int, end_index: int, ranges: list[tuple[int, int]]) -> bool:
    for range_start, range_end in ranges:
        if start_index < range_end and end_index > range_start:
            return True
    return False


def find_line_summary_ranges(text: str) -> list[tuple[int, int]]:
    match = LINE_SUMMARY_PATTERN.search(text)
    if not match:
        return []
    return[(match.start(), match.end())]


def strip_citation_labels(text: str) -> str:
    # 使用迴圈來清除可能因插入重疊而產生的巢狀標籤 (例如 [[18]4])
    prev = None
    while prev != text:
        prev = text
        text = CITATION_LABEL_RE.sub("", text)
    return text


def add_inline_citations(response: Any, excluded_ranges: list[tuple[int, int]] | None = None) -> str:
    text = response.text or ""
    excluded_ranges = excluded_ranges or[]

    try:
        supports = response.candidates[0].grounding_metadata.grounding_supports
        chunks = response.candidates[0].grounding_metadata.grounding_chunks
    except Exception:
        return text

    if not supports or not chunks:
        return text

    sorted_supports = sorted(
        supports,
        key=lambda s: s.segment.end_index if s.segment and s.segment.end_index is not None else 0,
        reverse=True,
    )

    for support in sorted_supports:
        segment = getattr(support, "segment", None)
        end_index = getattr(segment, "end_index", None)
        if segment is None or end_index is None:
            continue

        start_index = getattr(segment, "start_index", None)
        start_index = start_index if start_index is not None else end_index
        if _segment_overlaps_ranges(start_index, end_index, excluded_ranges):
            continue

        if not support.grounding_chunk_indices:
            continue

        citation_labels: list[str] = []
        seen_labels: set[int] = set()
        for idx in support.grounding_chunk_indices:
            if idx in seen_labels:
                continue
            if 0 <= idx < len(chunks):
                web_obj = getattr(chunks[idx], "web", None)
                uri = getattr(web_obj, "uri", None) if web_obj else None
                if uri:
                    citation_labels.append(f"[{idx + 1}]")
                    seen_labels.add(idx)
        if citation_labels:
            text = text[:end_index] + "".join(citation_labels) + text[end_index:]
    return text

def extract_grounding_sources(response: Any) -> list[tuple[str, str]]:
    try:
        chunks = response.candidates[0].grounding_metadata.grounding_chunks
    except Exception:
        return []

    sources: list[tuple[str, str]] = []
    seen: set[str] = set()
    for chunk in chunks or[]:
        web_obj = getattr(chunk, "web", None)
        if not web_obj:
            continue
        title = getattr(web_obj, "title", "") or ""
        uri = getattr(web_obj, "uri", "") or ""
        if uri and uri not in seen:
            seen.add(uri)
            sources.append((title, uri))
    return sources


def build_recent_rows_text(rows: list[StockRow], max_rows: int = 10) -> str:
    selected = rows[-max_rows:]
    return "\n".join(
        f"{format_date(row.trade_date)} | 收盤 {row.close_raw} | 漲跌 {row.change_raw} | 成交股數 {row.volume_raw}"
        for row in selected
    )


def extract_line_summary(analysis_text: str) -> tuple[str, str]:
    match = LINE_SUMMARY_PATTERN.search(analysis_text)

    summary_body = ""
    cleaned_analysis = analysis_text
    if match:
        summary_body = strip_citation_labels(match.group(1)).strip()
        cleaned_analysis = LINE_SUMMARY_PATTERN.sub("", analysis_text, count=1).strip()

    cleaned_analysis = re.sub(r"\n{3,}", "\n\n", cleaned_analysis).strip()

    # 移除結尾處的水平分隔線 (如 ---) 以及跟隨在後的 citation labels
    cleaned_analysis = re.sub(r"\n[-_*]{3,}\s*(?:\[[\d\[\]]+\]\s*)*$", "", cleaned_analysis).strip()
    # 移除結尾處連續 2 個以上的 citation labels 叢集
    cleaned_analysis = re.sub(r"(?:\[[\d\[\]]+\]\s*){2,}$", "", cleaned_analysis).strip()

    if not summary_body:
        lines =[
            strip_citation_labels(line).strip()
            for line in cleaned_analysis.splitlines()
            if strip_citation_labels(line).strip()
        ]
        summary_candidates = lines[:MAX_LINE_SUMMARY_LINES]
        summary_body = "\n".join(f"- {line[:120]}" for line in summary_candidates)

    normalized_lines: list[str] =[]
    for raw_line in summary_body.splitlines():
        line = strip_citation_labels(raw_line).strip("-•● ").strip()
        if not line:
            continue
        normalized_lines.append(f"- {line}")
        if len(normalized_lines) >= MAX_LINE_SUMMARY_LINES:
            break

    if not normalized_lines:
        normalized_lines = ["- 本日未成功擷取 LINE 摘要，請改看完整報告。"]

    summary_text = "\n".join(normalized_lines).strip()
    return cleaned_analysis, summary_text

def save_grounding_cache(today: date, sources: list[tuple[str, str]]) -> None:
    payload = {
        "report_date": format_date(today),
        "cached_at": taipei_now().isoformat(),
        "sources":[{"title": title, "url": url} for title, url in sources],
    }
    write_json(LATEST_NEWS_CACHE_PATH, payload)


def upsert_history_csv(rows: list[StockRow]) -> None:
    fieldnames =[
        "trade_date",
        "volume_raw",
        "amount_raw",
        "open_raw",
        "high_raw",
        "low_raw",
        "close_raw",
        "change_raw",
        "trades_raw",
    ]
    dedup: dict[str, dict[str, str]] = {}
    for row in rows:
        dedup[format_date(row.trade_date)] = {
            "trade_date": format_date(row.trade_date),
            "volume_raw": row.volume_raw,
            "amount_raw": row.amount_raw,
            "open_raw": row.open_raw,
            "high_raw": row.high_raw,
            "low_raw": row.low_raw,
            "close_raw": row.close_raw,
            "change_raw": row.change_raw,
            "trades_raw": row.trades_raw,
        }

    ordered_rows = [dedup[key] for key in sorted(dedup)]
    with TSMC_HISTORY_PATH.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ordered_rows)




RETRYABLE_GEMINI_STATUS_CODES = {429, 500, 503, 504}
RETRYABLE_GEMINI_MESSAGE_HINTS = (
    "resource_exhausted",
    "service unavailable",
    "temporarily overloaded",
    "temporarily running out of capacity",
    "model is overloaded",
    "deadline_exceeded",
    "timed out",
    "timeout",
    "unavailable",
    "internal",
)


def _extract_gemini_error_details(exc: Exception) -> tuple[int | None, str]:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.isdigit():
        code = int(code)
    elif not isinstance(code, int):
        code = None

    parts: list[str] = []
    message = getattr(exc, "message", None)
    if message:
        parts.append(str(message))
    if str(exc) and str(exc) not in parts:
        parts.append(str(exc))

    detail = " | ".join(part for part in parts if part).strip()
    return code, detail


def is_retryable_gemini_error(exc: Exception) -> bool:
    if isinstance(exc, errors.ServerError):
        return True

    code, detail = _extract_gemini_error_details(exc)
    if isinstance(exc, errors.APIError) and code in RETRYABLE_GEMINI_STATUS_CODES:
        return True

    lowered = detail.lower()
    return any(hint in lowered for hint in RETRYABLE_GEMINI_MESSAGE_HINTS)



def get_thinking_budget_for_model(model_name: str) -> int:
    normalized = (model_name or "").strip().lower()
    if normalized == FALLBACK_GEMINI_MODEL.strip().lower():
        return GEMINI_THINKING_BUDGET_FALLBACK
    if normalized == PRIMARY_GEMINI_MODEL.strip().lower():
        return GEMINI_THINKING_BUDGET_PRIMARY
    if "flash-lite" in normalized:
        return GEMINI_THINKING_BUDGET_FALLBACK
    return GEMINI_THINKING_BUDGET_PRIMARY


def build_generate_content_config(*, model_name: str) -> Any:
    thinking_budget = get_thinking_budget_for_model(model_name)
    tools = [types.Tool(google_search=types.GoogleSearch())]

    # 依官方 Gemini Thinking 文件，2.5 Flash-Lite 在未設定 thinkingBudget 時預設不會思考；
    # 因此這裡明確傳入 thinking_config，避免 fallback model 使用預設行為 (不思考)。
    try:
        thinking_config: Any = types.ThinkingConfig(
            thinking_budget=thinking_budget,
            include_thoughts=GEMINI_INCLUDE_THOUGHTS,
        )
    except Exception:
        thinking_config = {
            "thinking_budget": thinking_budget,
            "include_thoughts": GEMINI_INCLUDE_THOUGHTS,
        }

    try:
        return types.GenerateContentConfig(
            tools=tools,
            thinking_config=thinking_config,
        )
    except Exception:
        return {
            "tools": tools,
            "thinking_config": thinking_config,
        }


def call_gemini_with_google_search(
    *,
    client: genai.Client,
    model_name: str,
    prompt: str,
) -> Any:
    return client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=build_generate_content_config(model_name=model_name),
    )


def generate_analysis(
    *,
    today: date,
    latest_row: StockRow,
    today_has_new_data: bool,
    market_should_open: bool,
    market_event: HolidayEvent | None,
    recent_rows: list[StockRow],
) -> AnalysisResult:
    gemini_api_key = get_required_env("GEMINI_API_KEY")
    client = genai.Client(api_key=gemini_api_key)

    market_line = format_market_status(today_has_new_data, market_should_open, market_event)

    prompt = textwrap.dedent(
        f"""
        你現在是一位精通 IT、CS、全球總體經濟與台灣科技業的資深外資首席分析師。請以繁體中文撰寫一份給個人投資者閱讀的深度分析報告，主題是台股台積電(2330)。

        你須使用 Google Search grounding，檢索「各領域的最新與近期新聞動態」，並強制要求你的分析須採用「由上而下（Top-Down）」的四大維度框架進行綜合考量：
        1. 全球地緣政治與系統性風險：包含近期任何可能影響全球原物料供應鏈、能源價格、運輸、通膨預期、科技電子股估值、或引發市場避險情緒的國際事件，或相關的國際突發事件。
        必查主題包含但不限於：武裝衝突或停火破裂、制裁與反制裁、關鍵運輸通道或地點受阻、能源設施受威脅、重大恐怖攻擊、跨國網路攻擊、出口管制升級、政變或重大政局動盪、影響供應鏈的跨境政策衝突。
        若存在重大事件，須明確指出：
        ● 事件名稱或主流媒體常見稱呼
        ● 主要參與方
        ● 對能源價格 / 運輸 / 避險情緒 / 美金 / 殖利率 / 半導體估值的傳導路徑
        ● 對明日、一週、一個月、三個月、半年的不同權重
        不可僅以「地緣政治風險升溫」等空泛語句帶過。
        若查無足以影響市場定價的重要事件，才可明確寫出「近 30 日未見足以改變市場定價的重大地緣政治風險事件」。
        2. 全球總體經濟與資金面：如美聯儲（Fed）動向、美債殖利率、匯率波動等。
        3. 半導體產業週期與科技巨頭動態：如 AI 伺服器需求、美國政策 / 關稅 / 出口管制、主要客戶與供應鏈狀況。
        4. 台積電個股基本面、籌碼面與技術面：包含近期重大公告、法人觀點與量價結構。

        【強制覆蓋要求】
        進行 Google Search grounding 時，至少覆蓋以下四類查詢：
        A. 全球地緣政治、能源與運輸風險
        B. 美國利率、殖利率、美元與資金流向
        C. 半導體產業鏈、出口管制、AI 需求與主要客戶
        D. 台積電公告、法人觀點、籌碼與技術面
        若上述 A 類存在重大事件，則在總結段、利多利空段、以及明日 / 一週 / 一個月等三個時間框架中，皆須提及。

        【範例】
        正確寫法：
        「近期 xx 地區風險仍是短期市場重要變數。若 α 國、β 國、μ 國相關衝突升高，或 yy 運輸受阻，將先透過能源價格與避險情緒衝擊全球科技電子股估值，再間接影響台積電短期股價表現；因此其對明日與未來一週權重高於未來半年。」
        錯誤寫法：
        「近期仍有國際事件影響市場，須留意地緣政治風險。」

        【補充範例】
        若近 30 日相關事件僅屬短暫新聞雜訊、未對能源價格、運輸、避險情緒、美元、殖利率或半導體估值造成明顯外溢影響，則可寫：
        「近 30 日雖有零星地緣政治新聞，但尚未形成足以改變市場定價的重要系統性風險，故本期對台積電股價推演之權重較低。」

        請將上述重要來源與維度納入分析，並注意短期變數（如地緣政治避險）與中長期變數（如 AI 需求基本面）對不同時間框架預測的權重影響。

        【今日狀態】
        {market_line}

        【最新成交資料】
        最近一個成交日：{format_date(latest_row.trade_date)}
        最近收盤價：{latest_row.close_raw}
        最近漲跌價差：{latest_row.change_raw}
        最近成交股數：{latest_row.volume_raw}
        最近成交金額：{latest_row.amount_raw}
        開盤價：{latest_row.open_raw}
        最高價：{latest_row.high_raw}
        最低價：{latest_row.low_raw}
        成交筆數：{latest_row.trades_raw}

        【近十個交易日摘要】
        {build_recent_rows_text(recent_rows, max_rows=10)}

        【必須輸出的內容】
        1. 總結（請融合四大維度的核心觀點）
        2. 明日漲跌幅（給範圍，例如 -2% ~ +1%，並說明推演理由）
        3. 未來一週漲跌幅（給範圍與推演理由）
        4. 未來一個月漲跌幅（給範圍與推演理由）
        5. 未來三個月漲跌幅（給範圍與推演理由）
        6. 未來半年漲跌幅（給範圍與推演理由）
        7. 可能買點（用情境方式寫，不可假裝知道未來，並給出具體價位區間或技術指標條件）
        8. 可能賣點（用情境方式寫，不可假裝知道未來，並給出具體價位區間或技術指標條件）
        9. 利多因素
        10. 利空因素
        11. 關鍵觀察指標
        12. 風險提醒
        13. 信心等級（低 / 中 / 高）與理由

        【額外要求】
        報告正文結束後，請額外輸出一段給 LINE 使用的短摘要，且務必完全使用以下標記包住：
        <<<LINE_SUMMARY>>>
        - 每行一個重點
        - 共 10 行
        - 可包含明日 / 一週 / 一個月 / 三個月 / 半年趨勢、可能買賣點、主要利多利空、風險提醒
        - 內容需精簡，避免單行太長
        <<<END_LINE_SUMMARY>>>

        【寫作要求】
        - 不可只寫結論，必須寫推理依據（請善用四大維度框架推演短中長期邏輯）。
        - 若新聞彼此矛盾，須寫出矛盾點。
        - 不可寫成保證獲利。
        - 避免空泛形容詞，盡量明確。
        - 文字盡量詳細，但不要廢話。
        """
    ).strip()

    attempted_models: list[str] = []
    fallback_reason = ""
    response = None
    used_model = PRIMARY_GEMINI_MODEL
    used_thinking_budget = get_thinking_budget_for_model(PRIMARY_GEMINI_MODEL)
    fallback_used = False

    for idx, model_name in enumerate([PRIMARY_GEMINI_MODEL, FALLBACK_GEMINI_MODEL]):
        if model_name in attempted_models:
            continue
        attempted_models.append(model_name)
        try:
            response = call_gemini_with_google_search(
                client=client,
                model_name=model_name,
                prompt=prompt,
            )
            used_model = model_name
            used_thinking_budget = get_thinking_budget_for_model(model_name)
            fallback_used = idx > 0
            break
        except Exception as exc:
            code, detail = _extract_gemini_error_details(exc)
            logging.warning(
                "Gemini 模型呼叫失敗：model=%s | code=%s | detail=%s",
                model_name,
                code,
                detail or str(exc),
            )
            if idx == 0 and model_name != FALLBACK_GEMINI_MODEL and is_retryable_gemini_error(exc):
                fallback_reason = detail or (f"HTTP {code}" if code else str(exc))
                logging.info(
                    "主模型失敗，將切換到備用模型：primary=%s | fallback=%s",
                    PRIMARY_GEMINI_MODEL,
                    FALLBACK_GEMINI_MODEL,
                )
                continue
            raise

    if response is None:
        raise RuntimeError("Gemini 沒有回傳任何分析結果。")

    raw_text = (response.text or "").strip()
    excluded_ranges = find_line_summary_ranges(raw_text)
    cited_text = add_inline_citations(response, excluded_ranges=excluded_ranges).strip()
    analysis_text, summary_text = extract_line_summary(cited_text)
    sources = extract_grounding_sources(response)
    return AnalysisResult(
        analysis_text=analysis_text,
        summary_text=summary_text,
        grounding_sources=sources,
        primary_model=PRIMARY_GEMINI_MODEL,
        fallback_model=FALLBACK_GEMINI_MODEL,
        used_model=used_model,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        attempted_models=attempted_models,
        primary_thinking_budget=GEMINI_THINKING_BUDGET_PRIMARY,
        fallback_thinking_budget=GEMINI_THINKING_BUDGET_FALLBACK,
        used_thinking_budget=used_thinking_budget,
    )

def build_report(
    *,
    today: date,
    latest_row: StockRow,
    today_has_new_data: bool,
    market_should_open: bool,
    market_event: HolidayEvent | None,
    analysis_result: AnalysisResult,
) -> str:
    status_line = format_market_status(today_has_new_data, market_should_open, market_event)
    switch_line = "是" if analysis_result.fallback_used else "否"
    fallback_reason = analysis_result.fallback_reason.strip() or "未切換，主模型直接成功。"

    lines = [
        f"台積電({STOCK_NO})",
        f"今日日期：{format_date(today)}",
        status_line,
        "",
        "Gemini 模型使用資訊：",
        f"預設模型：{analysis_result.primary_model}",
        f"備用模型：{analysis_result.fallback_model}",
        f"本次實際使用：{analysis_result.used_model}",
        f"主模型 thinkingBudget：{analysis_result.primary_thinking_budget}",
        f"備用模型 thinkingBudget：{analysis_result.fallback_thinking_budget}",
        f"本次實際 thinkingBudget：{analysis_result.used_thinking_budget}",
        f"是否切換至備用模型：{switch_line}",
        f"模型切換原因：{fallback_reason}",
        f"本次嘗試順序：{' -> '.join(analysis_result.attempted_models)}",
        "案：關於 Thinking Budget，0 ▶ Disable Thinking，-1 ▶ Dynamic Thinking (模型自行決定使用多少 Token)。",
        "",
        f"最近一個成交日：{format_date(latest_row.trade_date)}",
        f"最近收盤價：{latest_row.close_raw}",
        f"最近漲跌價差：{latest_row.change_raw}",
        f"最近成交股數：{latest_row.volume_raw}",
        "",
        "分析：",
        analysis_result.analysis_text.strip() if analysis_result.analysis_text.strip() else "本次未取得分析內容。",
        "",
        "LINE 用短摘要：",
        analysis_result.summary_text.strip() if analysis_result.summary_text.strip() else "本次未取得 LINE 摘要。",
        "",
        "資料來源：",
        TWSE_STOCK_DAY_API,
        TWSE_STOCK_DAY_PAGE,
        TWSE_HOLIDAY_API,
        DGPA_CALENDAR_PAGE,
    ]

    if analysis_result.grounding_sources:
        lines.extend(["", "Gemini Google Search grounding 來源："])
        for idx, (title, uri) in enumerate(analysis_result.grounding_sources, start=1):
            lines.append(f"[{idx}] {(title.strip() or '(untitled)')} - {uri}")

    return "\n".join(lines).strip() + "\n"

def send_email(report_text: str, today: date) -> None:
    gmail_user = get_required_env("GMAIL_USER")
    gmail_app_password = get_required_env("GMAIL_APP_PASSWORD")
    recipients = parse_recipients(get_required_env("EMAIL_TO"))
    if not recipients:
        raise RuntimeError("EMAIL_TO 沒有任何有效收件人。")

    subject = f"台積電({STOCK_NO}) 每日報告 {format_date(today)}"

    msg = EmailMessage()
    msg["From"] = gmail_user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(report_text)

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(gmail_user, gmail_app_password)
        server.send_message(msg)


def main() -> int:
    today = taipei_now().date()
    logging.info("開始執行，today=%s", format_date(today))

    holiday_events = fetch_twse_holiday_events()
    market_should_open, market_event = get_market_open_status(today, holiday_events)

    recent_rows = collect_recent_stock_rows(STOCK_NO, today, lookback_months=3)
    latest_row, today_has_new_data = pick_latest_row(recent_rows, today)
    upsert_history_csv(recent_rows)

    analysis_result: AnalysisResult | None = None
    analysis_ok = False

    try:
        analysis_result = generate_analysis(
            today=today,
            latest_row=latest_row,
            today_has_new_data=today_has_new_data,
            market_should_open=market_should_open,
            market_event=market_event,
            recent_rows=recent_rows,
        )
        analysis_ok = True
    except Exception as exc:
        logging.exception("Gemini 分析失敗：%s", exc)
        analysis_result = AnalysisResult(
            analysis_text="Gemini 分析階段失敗，因此本次只寄送成交資料摘要。\n錯誤訊息：%s" % exc,
            summary_text="- Gemini 分析階段失敗，本次只提供成交資料。\n- 請查看完整報告中的錯誤訊息。",
            grounding_sources=[],
            primary_model=PRIMARY_GEMINI_MODEL,
            fallback_model=FALLBACK_GEMINI_MODEL,
            used_model=PRIMARY_GEMINI_MODEL,
            fallback_used=False,
            fallback_reason="主模型與備用模型皆未成功產出可用分析。",
            attempted_models=[PRIMARY_GEMINI_MODEL] if PRIMARY_GEMINI_MODEL == FALLBACK_GEMINI_MODEL else [PRIMARY_GEMINI_MODEL, FALLBACK_GEMINI_MODEL],
            primary_thinking_budget=GEMINI_THINKING_BUDGET_PRIMARY,
            fallback_thinking_budget=GEMINI_THINKING_BUDGET_FALLBACK,
            used_thinking_budget=GEMINI_THINKING_BUDGET_PRIMARY,
        )

    report_text = build_report(
        today=today,
        latest_row=latest_row,
        today_has_new_data=today_has_new_data,
        market_should_open=market_should_open,
        market_event=market_event,
        analysis_result=analysis_result,
    )

    paths = get_report_bundle_paths(today)
    write_text(paths["report"], report_text)
    write_text(paths["summary"], analysis_result.summary_text + "\n")
    save_grounding_cache(today, analysis_result.grounding_sources)

    meta_payload = {
        "report_date": format_date(today),
        "generated_at": taipei_now().isoformat(),
        "timezone": TIMEZONE,
        "stock_no": STOCK_NO,
        "gemini_model": analysis_result.used_model,
        "gemini_model_primary": analysis_result.primary_model,
        "gemini_model_fallback": analysis_result.fallback_model,
        "gemini_model_used": analysis_result.used_model,
        "gemini_thinking_budget_primary": analysis_result.primary_thinking_budget,
        "gemini_thinking_budget_fallback": analysis_result.fallback_thinking_budget,
        "gemini_thinking_budget_used": analysis_result.used_thinking_budget,
        "gemini_include_thoughts": GEMINI_INCLUDE_THOUGHTS,
        "gemini_fallback_used": analysis_result.fallback_used,
        "gemini_fallback_reason": analysis_result.fallback_reason,
        "gemini_attempted_models": analysis_result.attempted_models,
        "analysis_ok": analysis_ok,
        "today_has_new_data": today_has_new_data,
        "market_should_open": market_should_open,
        "market_event": asdict(market_event) if market_event else None,
        "latest_trade_date": format_date(latest_row.trade_date),
        "latest_close": latest_row.close_raw,
        "latest_change": latest_row.change_raw,
        "latest_volume": latest_row.volume_raw,
        "report_path": str(paths["report"]),
        "summary_path": str(paths["summary"]),
        "meta_path": str(paths["meta"]),
        "email_sent": False,
        "line_push_attempted": False,
        "line_push_sent": False,
        "line_push_error": "",
        "line_push_response":[],
        "status": "ok" if analysis_ok else "partial",
    }
    write_json(paths["meta"], meta_payload)
    logging.info("報告已寫入：%s", paths["report"])
    logging.info("摘要已寫入：%s", paths["summary"])
    logging.info("中繼資料已寫入：%s", paths["meta"])

    try:
        send_email(report_text, today)
        update_meta_flags(paths["meta"], email_sent=True)
        logging.info("Email 已寄出。")
    except Exception as exc:
        logging.exception("Email 寄送失敗：%s", exc)
        update_meta_flags(paths["meta"], email_sent=False, status="partial")

    line_push_enabled = getenv_bool("LINE_PUSH_ENABLED", False)
    line_push_only_if_new_data = getenv_bool("LINE_PUSH_ONLY_IF_NEW_DATA", False)
    should_push_line = line_push_enabled and (today_has_new_data or not line_push_only_if_new_data)

    if should_push_line:
        line_text = build_line_push_text(update_meta_flags(paths["meta"]), analysis_result.summary_text)
        try:
            responses = push_line_text_message(line_text)
            update_meta_flags(
                paths["meta"],
                line_push_attempted=True,
                line_push_sent=True,
                line_push_error="",
                line_push_response=responses,
            )
            logging.info("LINE 摘要已送出。")
        except Exception as exc:
            logging.exception("LINE 推播失敗：%s", exc)
            update_meta_flags(
                paths["meta"],
                line_push_attempted=True,
                line_push_sent=False,
                line_push_error=str(exc),
                status="partial",
            )
    else:
        update_meta_flags(
            paths["meta"],
            line_push_attempted=False,
            line_push_sent=False,
        )
        logging.info("LINE 推播已略過。enabled=%s | only_if_new_data=%s", line_push_enabled, line_push_only_if_new_data)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.exception("程式執行失敗：%s", exc)
        raise
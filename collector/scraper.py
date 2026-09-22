"""
みんレポ(min-repo.com)から ACT GOLD長浜 のスロット台データを取得するモジュール。

サイトはJavaScriptで描画されるため、requestsではなくPlaywright(ヘッドレスブラウザ)
でレンダリング後のDOMを読む。テーブルの列見出し(台番・差枚・G数...)をキーに
汎用的にパースするため、サイト側のCSSクラス名が変わってもある程度は耐える設計。

【重要】このコードは実際のサイトに対して一度も実行できていません(この開発環境は
ネットワークアクセスができないため)。ユーザーが共有したスクリーンショットの構造を
もとに書いていますが、実際にGitHub Actions上で動かして初めて検証できます。
最初の数回の実行結果(特に失敗時のスクリーンショット/HTML)を共有してもらえれば、
セレクタなどを調整します。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("collector.scraper")

# 列見出しの日本語 → 内部フィールド名
COLUMN_MAP = {
    "台番": "unit_number",
    "差枚": "diff_medals",
    "G数": "game_count",
    "出率": "payout_rate",
    "BB": "bb_count",
    "RB": "rb_count",
    "合成": "composite_denom",
    "BB率": "bb_rate_denom",
    "RB率": "rb_rate_denom",
}

# "1/109" のような分数表記から分母だけを取り出す
_FRACTION_RE = re.compile(r"1\s*/\s*([\d,]+)")
# ページ内のどこかにある日付表記 (例: 2026年7月22日, 2026/07/22, 07-22 等) を拾う
_DATE_PATTERNS = [
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"),
    re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})"),
]


@dataclass
class MachineRow:
    machine_name: str
    unit_number: int
    diff_medals: Optional[int] = None
    game_count: Optional[int] = None
    payout_rate: Optional[float] = None
    bb_count: Optional[int] = None
    rb_count: Optional[int] = None
    composite_denom: Optional[int] = None
    bb_rate_denom: Optional[int] = None
    rb_rate_denom: Optional[int] = None


@dataclass
class DayReport:
    report_date: Optional[date]
    source_url: str
    rows: list[MachineRow] = field(default_factory=list)
    prev_day_url: Optional[str] = None  # 「前日 >>」ボタンのリンク先


def _parse_int(text: str) -> Optional[int]:
    text = text.strip().replace(",", "")
    if text in ("", "-", "ー", "―"):
        return None
    try:
        # マイナス値 (△1,234 や -1,234) にも対応
        text = text.replace("△", "-")
        return int(text)
    except ValueError:
        return None


def _parse_float(text: str) -> Optional[float]:
    text = text.strip().replace("%", "").replace(",", "")
    if text in ("", "-", "ー", "―"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_fraction_denom(text: str) -> Optional[int]:
    m = _FRACTION_RE.search(text)
    if not m:
        return None
    return _parse_int(m.group(1))


def _extract_date_from_text(text: str) -> Optional[date]:
    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            try:
                return date(y, mo, d)
            except ValueError:
                continue
    return None


async def _find_prev_day_url(page: Page) -> Optional[str]:
    """「前日 >>」ボタンのhrefを探す。複数の言い回し・実装に備えて緩めに探索する。"""
    candidates = [
        "text=前日",
        "a:has-text('前日')",
        "button:has-text('前日')",
    ]
    for sel in candidates:
        try:
            el = page.locator(sel).first
            if await el.count() == 0:
                continue
            href = await el.get_attribute("href")
            if href:
                return href
            # ボタン形式でクリックが必要な場合はここでは扱わず、
            # main.py 側でクリック遷移するフォールバックに任せる。
        except Exception:
            continue
    return None


async def scrape_report_page(page: Page, url: str, timeout_ms: int = 30000) -> DayReport:
    """指定したmin-repoの個別レポートURLからスロット台データ一覧を取得する。"""
    logger.info("Navigating to %s", url)
    await page.goto(url, wait_until="networkidle", timeout=timeout_ms)

    # データ一覧の表が描画されるまで待つ。サイト内に "台番" という文字が
    # 出現するテーブルヘッダがあるはずなので、それを待機条件にする。
    try:
        await page.wait_for_selector("text=台番", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        logger.warning("「台番」ヘッダが見つかりませんでした: %s（データなし、または構造変更の可能性）", url)

    page_text = await page.inner_text("body")
    report_date = _extract_date_from_text(page_text)

    rows: list[MachineRow] = []

    tables = page.locator("table")
    table_count = await tables.count()
    logger.info("Found %d <table> elements on %s", table_count, url)

    for i in range(table_count):
        table = tables.nth(i)
        header_cells = table.locator("thead tr th, tr:first-child th, tr:first-child td")
        header_texts = [t.strip() for t in await header_cells.all_inner_texts()]

        if "台番" not in header_texts or "差枚" not in header_texts:
            continue  # データ一覧の表ではない(グラフの凡例テーブルなど)

        col_index = {}
        for idx, h in enumerate(header_texts):
            field_name = COLUMN_MAP.get(h)
            if field_name:
                col_index[field_name] = idx

        # このテーブルの機種名を推定: テーブル直前にある見出し要素のテキストから
        # "◯◯　データ一覧" のパターンを拾う
        machine_name = await _guess_machine_name(table)

        body_rows = table.locator("tbody tr")
        if await body_rows.count() == 0:
            body_rows = table.locator("tr").nth_range(1, None)  # ヘッダを除く全行 (フォールバック)

        row_count = await body_rows.count()
        for r in range(row_count):
            tr = body_rows.nth(r)
            cells = [c.strip() for c in await tr.locator("td").all_inner_texts()]
            if not cells or len(cells) < 2:
                continue

            def cell(field_name: str) -> Optional[str]:
                idx = col_index.get(field_name)
                if idx is None or idx >= len(cells):
                    return None
                return cells[idx]

            unit_raw = cell("unit_number")
            if unit_raw is None or unit_raw in ("平均", "合計", ""):
                continue  # 「平均」行はサマリなのでスキップ

            unit_number = _parse_int(unit_raw)
            if unit_number is None:
                continue

            rows.append(
                MachineRow(
                    machine_name=machine_name,
                    unit_number=unit_number,
                    diff_medals=_parse_int(cell("diff_medals") or ""),
                    game_count=_parse_int(cell("game_count") or ""),
                    payout_rate=_parse_float(cell("payout_rate") or ""),
                    bb_count=_parse_int(cell("bb_count") or ""),
                    rb_count=_parse_int(cell("rb_count") or ""),
                    composite_denom=_parse_fraction_denom(cell("composite_denom") or ""),
                    bb_rate_denom=_parse_fraction_denom(cell("bb_rate_denom") or ""),
                    rb_rate_denom=_parse_fraction_denom(cell("rb_rate_denom") or ""),
                )
            )

    prev_day_url = await _find_prev_day_url(page)

    return DayReport(report_date=report_date, source_url=url, rows=rows, prev_day_url=prev_day_url)


async def _guess_machine_name(table) -> str:
    """テーブル要素の直前にある見出しテキストから機種名を推定する。
    見出しの文言は「◯◯　データ一覧」の形式を想定 (画面例より)。
    見つからない場合は "unknown" を返す。
    """
    try:
        heading = table.locator(
            "xpath=preceding::*[contains(text(), 'データ一覧')][1]"
        )
        if await heading.count() > 0:
            text = (await heading.first.inner_text()).strip()
            return re.sub(r"\s*データ一覧\s*$", "", text).strip() or "unknown"
    except Exception:
        pass
    return "unknown"


async def find_latest_report_url(page: Page, tag_url: str, timeout_ms: int = 30000) -> Optional[str]:
    """ホールのタグ一覧ページ(例: /tag/act-gold長浜/)から、
    最新レポートへのリンクを1件取得する。

    一覧ページは新しい順に並んでいる前提。個別レポートのURLは
    "https://min-repo.com/<数字>/" の形式であることを利用し、
    本文中のリンクからそれらしいものを最初に見つかったものを返す。
    """
    logger.info("Navigating to tag page %s", tag_url)
    await page.goto(tag_url, wait_until="networkidle", timeout=timeout_ms)

    try:
        await page.wait_for_selector("a[href]", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        logger.warning("タグ一覧ページでリンクが見つかりませんでした: %s", tag_url)
        return None

    hrefs = await page.locator("a[href]").evaluate_all("els => els.map(e => e.href)")
    report_url_re = re.compile(r"^https://min-repo\.com/\d+/?$")
    for href in hrefs:
        if report_url_re.match(href):
            return href
    return None


async def new_page(headless: bool = True):
    """Playwrightのブラウザ・コンテキスト・ページを生成するヘルパー。
    呼び出し側で `async with` して使う。
    """
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=headless)
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        viewport={"width": 390, "height": 844},
        locale="ja-JP",
    )
    page = await context.new_page()
    return playwright, browser, context, page

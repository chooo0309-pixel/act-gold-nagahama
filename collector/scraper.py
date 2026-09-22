"""
ACT GOLD長浜のスロットデータをmin-repo.comから収集するスクレイパー。

min-repo.comはJavaScriptでレンダリングされるため、Playwrightの
ヘッドレスブラウザを使用する。

これまでの調査で判明したこと:
- 個別レポートページ(例: https://min-repo.com/3363553/)には、
  台番ごとの個別データそのものは無く、「全台データ一覧・差枚ランキング」
  というリンク(href: "?kishu=all")の先に個別台データ一覧がある。
- そのURL(<report_url>?kishu=all)には、
  header=['機種','台番','差枚','G数','出率'] の5列・約300行超のテーブルがある。
  BB/RB/合成等の列は含まれていない(スキーマ上NULL許容なのでそのまま欠損として扱う)。
- そのURLへ直接アクセスすると、site側のBot対策/レート制限と思われる理由で
  「テーブル0件・本文0文字」が返ってくることがある(頻度は不定、再試行すると
  成功することが多い)。そのため必ずリトライ処理を挟む。
- page.goto(..., wait_until="networkidle") はこのサイトでは高確率でタイムアウトする
  (広告等が継続的に通信するため)。wait_until="domcontentloaded" + 明示的なtimeoutを使う。
- 前日/翌日リンクのhrefは相対URLで書かれていることがあるため、
  get_attribute("href") ではなく evaluate("el => el.href") で
  ブラウザ解決後の絶対URLを取得する。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from playwright.async_api import async_playwright

logger = logging.getLogger("collector.scraper")

NAV_TIMEOUT_MS = 45000
RETRY_COUNT = 4
RETRY_DELAY_MS = 6000

# 個別台データ表のヘッダー -> 内部フィールド名
COLUMN_MAP = {
    "機種": "machine_name",
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


@dataclass
class MachineRow:
    machine_name: str
    unit_number: int
    diff_medals: int | None = None
    game_count: int | None = None
    payout_rate: float | None = None
    bb_count: int | None = None
    rb_count: int | None = None
    composite_denom: int | None = None
    bb_rate_denom: int | None = None
    rb_rate_denom: int | None = None


@dataclass
class DayReport:
    report_date: date
    source_url: str
    rows: list[MachineRow] = field(default_factory=list)


def _parse_int(text: str) -> int | None:
    if text is None:
        return None
    t = text.strip().replace(",", "")
    if t in ("", "-", "--", "―", "N/A"):
        return None
    m = re.match(r"^[+\-]?\d+$", t)
    if not m:
        return None
    return int(t)


def _parse_float(text: str) -> float | None:
    if text is None:
        return None
    t = text.strip().replace(",", "").replace("%", "")
    if t in ("", "-", "--", "―", "N/A"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _parse_fraction_denom(text: str) -> int | None:
    """'89/304' のような分数表記から分母(または分子)を int で取り出す補助関数。
    現状の個別台一覧の列には使わないが、将来 BB/RB 率が出てきた場合のために残す。"""
    if text is None:
        return None
    t = text.strip()
    m = re.match(r"^(\d+)\s*/\s*(\d+)$", t)
    if not m:
        return _parse_int(t)
    return int(m.group(2))


def _extract_date_from_text(text: str) -> date | None:
    """'2026年9月21日' や '9/20(日)' のような表記から date を抽出する。"""
    if not text:
        return None
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


async def new_page(headless: bool = True):
    """Playwrightのbrowser/context/pageをiPhone風UAで初期化する。"""
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=headless)
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.5 Mobile/15E148 Safari/604.1"
        ),
        viewport={"width": 390, "height": 844},
        locale="ja-JP",
    )
    page = await context.new_page()
    return playwright, browser, context, page


async def _find_all_units_link(page) -> str | None:
    """「全台データ一覧・差枚ランキング」リンクのhrefを解決済み絶対URLで返す。"""
    candidates = page.locator(
        "a:has-text('全台データ一覧'), button:has-text('全台データ一覧')"
    )
    count = await candidates.count()
    if count == 0:
        return None
    href = await candidates.first.evaluate("el => el.href || null")
    return href


async def _dump_unit_table(page) -> list[MachineRow] | None:
    """ページ内の<table>から、台番ごとの個別データ表を見つけてパースする。
    対象テーブルは header に '台番' を含み、行数が最大のものとする。"""
    tables = page.locator("table")
    table_count = await tables.count()
    if table_count == 0:
        return None

    target = None
    max_rows = -1
    for i in range(table_count):
        table = tables.nth(i)
        header_cells = table.locator("tr:first-child th, tr:first-child td")
        header_texts = [t.strip() for t in await header_cells.all_inner_texts()]
        if "台番" not in header_texts:
            continue
        row_count = max(0, await table.locator("tr").count() - 1)
        if row_count > max_rows:
            max_rows = row_count
            target = table
            target_headers = header_texts

    if target is None:
        return None

    field_order = [COLUMN_MAP.get(h) for h in target_headers]

    rows_locator = target.locator("tr")
    total_rows = await rows_locator.count()
    results: list[MachineRow] = []

    for i in range(1, total_rows):  # 0行目はヘッダーなのでスキップ
        cells = rows_locator.nth(i).locator("td, th")
        texts = [t.strip() for t in await cells.all_inner_texts()]
        if len(texts) != len(field_order):
            continue

        values: dict[str, str] = {}
        for field_name, text in zip(field_order, texts):
            if field_name:
                values[field_name] = text

        unit_number = _parse_int(values.get("unit_number", ""))
        machine_name = values.get("machine_name", "").strip()
        if unit_number is None or not machine_name:
            # 台番または機種名が読み取れない行は捨てる(ヘッダー再掲や広告行などの可能性)
            continue

        row = MachineRow(
            machine_name=machine_name,
            unit_number=unit_number,
            diff_medals=_parse_int(values.get("diff_medals", "")),
            game_count=_parse_int(values.get("game_count", "")),
            payout_rate=_parse_float(values.get("payout_rate", "")),
            bb_count=_parse_int(values.get("bb_count", "")) if "bb_count" in values else None,
            rb_count=_parse_int(values.get("rb_count", "")) if "rb_count" in values else None,
            composite_denom=_parse_fraction_denom(values.get("composite_denom", "")) if "composite_denom" in values else None,
            bb_rate_denom=_parse_fraction_denom(values.get("bb_rate_denom", "")) if "bb_rate_denom" in values else None,
            rb_rate_denom=_parse_fraction_denom(values.get("rb_rate_denom", "")) if "rb_rate_denom" in values else None,
        )
        results.append(row)

    return results


async def scrape_report_page(page, report_url: str) -> DayReport:
    """1日分のレポートページから、台番ごとの個別データを収集する。

    手順:
    1. レポートページ本体に遷移(日付抽出・前日リンク取得のため)
    2. 「全台データ一覧・差枚ランキング」リンクのURLを取得
    3. そのURLへ、レポートページをrefererとして遷移
    4. site側の一時的なブロックに備えて、台番テーブルが見つかるまでリトライ
    """
    logger.info("レポートページへ遷移: %s", report_url)
    await page.goto(report_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    await page.wait_for_timeout(1500)

    body_text = await page.inner_text("body")
    report_date = _extract_date_from_text(body_text) or _extract_date_from_text(await page.title())

    all_units_url = await _find_all_units_link(page)
    if all_units_url is None:
        raise RuntimeError(f"「全台データ一覧」リンクが見つかりません: {report_url}")

    rows: list[MachineRow] | None = None
    last_error: Exception | None = None

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            logger.info(
                "全台データ一覧へ遷移 (試行 %d/%d): %s", attempt, RETRY_COUNT, all_units_url
            )
            await page.goto(
                all_units_url,
                wait_until="domcontentloaded",
                timeout=NAV_TIMEOUT_MS,
                referer=report_url,
            )
            await page.wait_for_timeout(2000)

            rows = await _dump_unit_table(page)
            if rows:
                logger.info("台番データ取得成功: %d行 (試行 %d)", len(rows), attempt)
                break
            else:
                logger.warning(
                    "台番データが0件でした(サイト側の一時的な制限の可能性)。リトライします。 (試行 %d/%d)",
                    attempt, RETRY_COUNT,
                )
        except Exception as e:
            last_error = e
            logger.warning("全台データ一覧の取得中にエラー (試行 %d/%d): %r", attempt, RETRY_COUNT, e)

        if attempt < RETRY_COUNT:
            await page.wait_for_timeout(RETRY_DELAY_MS)
            # レポートページに戻ってからもう一度リンクを踏み直す(refererを正しく保つため)
            await page.goto(report_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            await page.wait_for_timeout(1500)

    if not rows:
        detail = f" (最後のエラー: {last_error!r})" if last_error else ""
        raise RuntimeError(
            f"{RETRY_COUNT}回試行しましたが台番データを取得できませんでした: {report_url}{detail}"
        )

    if report_date is None:
        raise RuntimeError(f"レポートページから日付を抽出できませんでした: {report_url}")

    return DayReport(report_date=report_date, source_url=report_url, rows=rows)


async def _find_prev_day_url(page) -> str | None:
    """「前日」リンクの絶対URLを返す。相対hrefのままだとナビゲーションに失敗するため、
    evaluate()でブラウザ解決済みの絶対URLを取得する。"""
    candidates = page.locator("a:has-text('前日')")
    count = await candidates.count()
    if count == 0:
        return None
    href = await candidates.first.evaluate("el => el.href || null")
    return href


async def find_latest_report_url(page, tag_url: str) -> str | None:
    """タグ一覧ページから最新のレポートURLを1件取得する。"""
    logger.info("タグ一覧ページへ遷移: %s", tag_url)
    await page.goto(tag_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    await page.wait_for_timeout(1500)

    links = page.locator("a[href^='https://min-repo.com/']")
    count = await links.count()
    pattern = re.compile(r"^https://min-repo\.com/\d+/?$")

    for i in range(count):
        href = await links.nth(i).evaluate("el => el.href || null")
        if href and pattern.match(href):
            return href

    return None

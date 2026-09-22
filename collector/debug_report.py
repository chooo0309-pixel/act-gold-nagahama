"""
診断用スクリプト3: 「全台データ一覧・差枚ランキング」ボタンの正体を調べる。

前回、hrefへ直接goto()すると総<table>数0・BODY TEXT 0文字になった。
リファラー無しの直接アクセスがブロックされている可能性があるため、
(A) refererを明示的に付けて直接遷移する方式と
(B) 実際にリンクをクリックする方式(refererは自動で付く)
の両方を試して比較する。
"""

from __future__ import annotations

import asyncio
import logging

from .scraper import new_page

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("collector.debug_report")

REPORT_URL = "https://min-repo.com/3363553/"


async def dump_tables(page, label: str) -> None:
    tables = page.locator("table")
    table_count = await tables.count()
    logger.info("=== [%s] 総<table>数: %d ===", label, table_count)
    for i in range(table_count):
        table = tables.nth(i)
        header_cells = table.locator("thead tr th, tr:first-child th, tr:first-child td")
        header_texts = [t.strip() for t in await header_cells.all_inner_texts()]
        row_count = await table.locator("tbody tr").count()
        if row_count == 0:
            row_count = max(0, await table.locator("tr").count() - 1)
        logger.info("[%s] table[%d]: header=%s rows=%d", label, i, header_texts, row_count)


async def main() -> None:
    playwright, browser, context, page = await new_page(headless=True)
    try:
        logger.info("=== Navigating to %s ===", REPORT_URL)
        await page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)

        candidates = page

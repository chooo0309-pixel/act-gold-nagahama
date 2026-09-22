"""
診断用スクリプト2: 個別レポートページ(1日分)を開いて、
実際にどれだけの<table>があるか、それぞれの見出し・行数を調べる。

全台データ一覧(ランキング)だけでなく、機種ごとの個別テーブルが
ページ下部にどれだけあるかを確認する。JSの遅延読み込みに備えて
スクロールもしてみる。
"""

from __future__ import annotations

import asyncio
import logging

from .scraper import new_page

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("collector.debug_report")

# 2026-09-20 のレポートページ(タグ一覧から取得した実際のURL)
REPORT_URL = "https://min-repo.com/3363553/"


async def main() -> None:
    playwright, browser, context, page = await new_page(headless=True)
    try:
        logger.info("=== Navigating to %s ===", REPORT_URL)
        await page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3000)

        # ページ最下部までスクロールして遅延読み込みを誘発する
        prev_height = 0
        for i in range(15):
            height = await page.evaluate("document.body.scrollHeight")
            if height == prev_height:
                break
            prev_height = height
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(800)

        logger.info("=== スクロール完了 ===")

        tables = page.locator("table")
        table_count = await tables.count()
        logger.info("=== 総<table>数: %d ===", table_count)

        for i in range(table_count):
            table = tables.nth(i)
            header_cells = table.locator("thead tr th, tr:first-child th, tr:first-child td")
            header_texts = [t.strip() for t in await header_cells.all_inner_texts()]
            row_count = await table.locator("tbody tr").count()
            if row_count == 0:
                row_count = max(0, await table.locator("tr").count() - 1)

            heading_text = ""
            try:
                heading = table.locator("xpath=preceding::*[self::h1 or self::h2 or self::h3 or self::div][1]")
                if await heading.count() > 0:
                    heading_text = (await heading.first.inner_text()).strip()[:50]
            except Exception:
                pass

            logger.info(
                "table[%d]: header=%s rows=%d heading='%s'",
                i, header_texts, row_count, heading_text,
            )

        body_text = await page.inner_text("body")
        logger.info("=== BODY TEXT 総文字数: %d ===", len(body_text))

    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())

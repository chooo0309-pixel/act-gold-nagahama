"""
診断用スクリプト4: kishu=all ページの個別台データ表(325行見つかった)の
実際の列構成を正確に調べる。ヘッダーがrowspan/colspanで複数行に
分かれている可能性があるため、theadの生HTMLと最初の数行のtbody
の生HTML/セル内容をダンプする。
"""

from __future__ import annotations

import asyncio
import logging

from .scraper import new_page

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("collector.debug_report")

REPORT_URL = "https://min-repo.com/3363553/"
ALL_URL = "https://min-repo.com/3363553/?kishu=all"


async def main() -> None:
    playwright, browser, context, page = await new_page(headless=True)
    try:
        logger.info("=== Navigating to %s ===", REPORT_URL)
        await page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(1500)

        logger.info("=== Navigating to %s (referer付き) ===", ALL_URL)
        await page.goto(ALL_URL, wait_until="domcontentloaded", timeout=45000, referer=REPORT_URL)
        await page.wait_for_timeout(2000)

        tables = page.locator("table")
        table_count = await tables.count()
        logger.info("=== 総<table>数: %d ===", table_count)
        target_index = None
        max_rows = -1
        for i in range(table_count):
            table = tables.nth(i)
            row_count = await table.locator("tbody tr").count()
            if row_count == 0:
                row_count = max(0, await table.locator("tr").count() - 1)
            logger.info("table[%d]: row_count=%d", i, row_count)
            if row_count > max_rows:
                max_rows = row_count
                target_index = i

        logger.info("=== 対象テーブル: table[%d] (rows=%d) ===", target_index, max_rows)
        target = tables.nth(target_index)

        try:
            thead = target.locator("thead")
            if await thead.count() > 0:
                thead_html = await thead.first.inner_html()
                logger.info("=== thead innerHTML ===\n%s", thead_html[:2000])
            else:
                logger.info("=== theadが存在しない ===")
        except Exception as e:
            logger.info("=== thead取得エラー: %r ===", e)

        try:
            first_rows = target.locator("tr")
            first_row_count = min(3, await first_rows.count())
            for i in range(first_row_count):
                row_html = await first_rows.nth(i).inner_html()
                logger.info("=== tr[%d] innerHTML ===\n%s", i, row_html[:1500])
        except Exception as e:
            logger.info("=== tr取得エラー: %r ===", e)

        try:
            body_rows = target.locator("tbody tr")
            body_row_count = min(3, await body_rows.count())
            if body_row_count == 0:
                all_rows = target.locator("tr")
                total = await all_rows.count()
                for i in range(1, min(4, total)):
                    cells = all_rows.nth(i).locator("td, th")
                    texts = [t.strip() for t in await cells.all_inner_texts()]
                    logger.info("data_row[%d] (%d cells): %s", i, len(texts), texts)
            else:
                for i in range(body_row_count):
                    cells = body_rows.nth(i).locator("td, th")
                    texts = [t.strip() for t in await cells.all_inner_texts()]
                    logger.info("tbody_row[%d] (%d cells): %s", i, len(texts), texts)
        except Exception as e:
            logger.info("=== data行取得エラー: %r ===", e)

    except Exception as e:
        logger.info("=== エラー発生: %r ===", e)
    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())

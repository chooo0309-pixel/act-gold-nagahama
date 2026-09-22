"""
テストスクリプト: 本番の scrape_report_page() を実際に1日分だけ実行して、
リトライ機構込みで正しくデータが取れるか確認する。Supabaseへの保存はしない。
"""

from __future__ import annotations

import asyncio
import logging

from .scraper import new_page, scrape_report_page

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("collector.debug_report")

REPORT_URL = "https://min-repo.com/3363553/"


async def main() -> None:
    playwright, browser, context, page = await new_page(headless=True)
    try:
        report = await scrape_report_page(page, REPORT_URL)
        logger.info("=== 収集成功 ===")
        logger.info("report_date: %s", report.report_date)
        logger.info("source_url: %s", report.source_url)
        logger.info("行数: %d", len(report.rows))
        for row in report.rows[:10]:
            logger.info(
                "台番%s %s 差枚=%s G数=%s 出率=%s",
                row.unit_number, row.machine_name, row.diff_medals, row.game_count, row.payout_rate,
            )
    except Exception as e:
        logger.error("=== 収集失敗: %r ===", e)
    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())

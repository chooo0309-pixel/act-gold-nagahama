"""
診断用スクリプト3: 「全台データ一覧・差枚ランキング」ボタンの正体を調べる。

前回のスクリーンショットで、このボタンが機種別/バラエティ/末尾別タブとは
別の独立したリンクになっていることが判明した。個別台(台番ごと)の
データ一覧はこのボタンの先にあると考えられる。

このスクリプトでは:
1. 該当リンクを探し、hrefやテキストをログ出力
2. リンクなら実際にそのURLへ遷移してテーブル構造を調べる
3. href が無く JS操作(onclick等)の場合はクリックしてみて、
   遷移後のURLとテーブル構造を調べる
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

        candidates = page.locator("a:has-text('全台データ一覧'), button:has-text('全台データ一覧')")
        count = await candidates.count()
        logger.info("=== '全台データ一覧'を含む要素数: %d ===", count)

        for i in range(count):
            el = candidates.nth(i)
            tag = await el.evaluate("el => el.tagName")
            text = (await el.inner_text()).strip()
            href = await el.evaluate("el => el.getAttribute('href')")
            resolved_href = await el.evaluate("el => el.href || null")
            onclick = await el.evaluate("el => el.getAttribute('onclick')")
            logger.info(
                "候補[%d]: tag=%s text=%r href=%r resolved_href=%r onclick=%r",
                i, tag, text, href, resolved_href, onclick,
            )

        if count == 0:
            logger.info("=== リンクが見つからなかった。処理終了 ===")
            return

        target = candidates.first
        resolved_href = await target.evaluate("el => el.href || null")

        if resolved_href and resolved_href.startswith("http"):
            logger.info("=== hrefへ直接遷移します: %s ===", resolved_href)
            await page.goto(resolved_href, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2000)
            logger.info("=== 遷移後 page.url: %s ===", page.url)
            await dump_tables(page, "遷移後")
        else:
            logger.info("=== hrefが取得できないためクリックを試みます ===")
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
                await target.click()
            logger.info("=== クリック後 page.url: %s ===", page.url)
            await page.wait_for_timeout(2000)
            await dump_tables(page, "クリック後")

        try:
            await page.screenshot(path="debug_report_screenshot.png", full_page=True)
            logger.info("=== スクリーンショット保存 ===")
        except Exception as e:
            logger.info("=== スクリーンショット失敗: %r ===", e)

        body_text = await page.inner_text("body")
        logger.info("=== BODY TEXT 総文字数: %d ===", len(body_text))

    except Exception as e:
        logger.info("=== エラー発生: %r ===", e)
        try:
            await page.screenshot(path="debug_report_screenshot.png", full_page=True)
        except Exception:
            pass
    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())

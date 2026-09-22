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
            logger.info("=== [方式A] refererを付けてhrefへ遷移します: %s ===", resolved_href)
            await page.goto(resolved_href, wait_until="domcontentloaded", timeout=45000, referer=REPORT_URL)
            await page.wait_for_timeout(2000)
            logger.info("=== [方式A] 遷移後 page.url: %s ===", page.url)
            await dump_tables(page, "方式A")

        logger.info("=== [方式B] 元のページに戻ってクリックします ===")
        await page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)
        target2 = page.locator("a:has-text('全台データ一覧'), button:has-text('全台データ一覧')").first
        try:
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
                await target2.click()
            logger.info("=== [方式B] クリック後 page.url: %s ===", page.url)
        except Exception as e:
            logger.info("=== [方式B] クリック時にナビゲーション検知できず: %r (page.url=%s) ===", e, page.url)
        await page.wait_for_timeout(2000)
        await dump_tables(page, "方式B")

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

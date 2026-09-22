"""
診断用スクリプト: min-repoのタグ一覧ページ(ホール別)を開いて、
実際にどんなリンク・日付表記が並んでいるかをログに出力する。

このスクリプトは一時的な調査用。本実装(main.py)の設計を
正しく決めるために、実際のページ構造をログで確認する。
"""

from __future__ import annotations

import asyncio
import logging

from .scraper import new_page

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("collector.debug_tag")

TAG_URL = "https://min-repo.com/tag/act-gold%E9%95%B7%E6%B5%9C/"


async def main() -> None:
    playwright, browser, context, page = await new_page(headless=True)
    try:
        logger.info("=== Navigating to %s ===", TAG_URL)
        await page.goto(TAG_URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3000)  # JSでの追加描画を少し待つ

        # ページ全体のテキストを先頭2000文字だけ出す(構造把握用)
        body_text = await page.inner_text("body")
        logger.info("=== BODY TEXT (先頭2000文字) ===")
        logger.info(body_text[:2000])

        # 個別レポートらしきリンク(数字だけのパス)を全部抽出
        anchors = page.locator("a[href]")
        count = await anchors.count()
        logger.info("=== 総リンク数: %d ===", count)

        report_links = []
        for i in range(count):
            a = anchors.nth(i)
            href = await a.evaluate("el => el.href")
            text = (await a.inner_text()).strip()
            if href and "min-repo.com/" in href:
                import re
                if re.match(r"^https://min-repo\.com/\d+/?$", href):
                    report_links.append((href, text))

        logger.info("=== レポートらしきリンク: %d 件 ===", len(report_links))
        for href, text in report_links[:60]:
            logger.info("%s | %s", href, text)

        # ページネーション(次のページ)らしき要素も探す
        logger.info("=== ページネーションらしき要素 ===")
        pagination_candidates = [
            "a:has-text('次')",
            "a:has-text('Next')",
            "a[rel=next]",
            ".pagination a",
            ".page-numbers",
        ]
        for sel in pagination_candidates:
            loc = page.locator(sel)
            c = await loc.count()
            if c > 0:
                texts = await loc.all_inner_texts()
                logger.info("selector=%s count=%d texts=%s", sel, c, texts[:10])

    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())

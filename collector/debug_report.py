 """
診断用スクリプト2 (改良版): 個別レポートページ(1日分)を開いて、
実際にどれだけの<table>があるか、それぞれの見出し・行数を調べる。

前回の実行で「総<table>数: 0」「BODY TEXT 総文字数: 0」という
異常な結果になったため、原因切り分けのために以下を追加でログ出力する:
- page.goto() 後の実際のURL (リダイレクトされていないか)
- ページタイトル
- HTTPレスポンスのステータスコード
- <body>のinnerHTML冒頭500文字 (真っ白なのか、何か別の内容が出ているのか)
- スクリーンショットをartifactとして保存 (実際に何が表示されているか目視確認できるように)
- 主要な要素(html, body, head)の存在確認
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
        response = await page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=45000)

        # レスポンスの状態を確認
        if response is not None:
            logger.info("=== HTTP status: %d ===", response.status)
            logger.info("=== response.url: %s ===", response.url)
        else:
            logger.info("=== response is None (ナビゲーションが応答を返さなかった) ===")

        logger.info("=== page.url (現在のURL): %s ===", page.url)

        try:
            title = await page.title()
            logger.info("=== page title: %r ===", title)
        except Exception as e:
            logger.info("=== page.title() でエラー: %r ===", e)

        await page.wait_for_timeout(3000)

        # この時点でのHTML冒頭を確認(空白ページか、Cloudflare的な確認画面か等)
        try:
            html_snippet = await page.content()
            logger.info("=== HTML長さ: %d文字 ===", len(html_snippet))
            logger.info("=== HTML冒頭800文字 ===\n%s", html_snippet[:800])
        except Exception as e:
            logger.info("=== page.content() でエラー: %r ===", e)

        # スクリーンショットを撮って実際の見た目を保存(artifactとしてアップロードする)
        try:
            await page.screenshot(path="debug_report_screenshot.png", full_page=True)
            logger.info("=== スクリーンショット保存: debug_report_screenshot.png ===")
        except Exception as e:
            logger.info("=== スクリーンショット失敗: %r ===", e)

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

        # スクロール後にもう一度スクリーンショット
        try:
            await page.screenshot(path="debug_report_screenshot_after_scroll.png", full_page=True)
            logger.info("=== スクロール後スクリーンショット保存 ===")
        except Exception as e:
            logger.info("=== スクロール後スクリーンショット失敗: %r ===", e)

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
        if len(body_text) > 0:
            logger.info("=== BODY TEXT 冒頭500文字 ===\n%s", body_text[:500])

    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())

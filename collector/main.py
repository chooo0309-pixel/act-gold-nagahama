"""
ACT GOLD長浜 スロット台データ収集 — CLIエントリーポイント

使い方:
    # 直近1日分を取得 (日次実行用)
    python -m collector.main daily

    # 指定期間をバックフィル (前日リンクを辿って遡る)
    python -m collector.main backfill --start 2026-07-22 --end 2026-09-21

    # 特定の1ページから手動で開始したい場合
    python -m collector.main backfill --start 2026-07-22 --end 2026-09-21 \
        --start-url https://min-repo.com/3365529/

環境変数:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime, timedelta

from .scraper import DayReport, find_latest_report_url, new_page, scrape_report_page
from .supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("collector.main")

TAG_URL = "https://min-repo.com/tag/act-gold%E9%95%B7%E6%B5%9C/"
MAX_BACKFILL_DAYS = 120  # 前日リンクを辿る回数の安全上限 (無限ループ防止)


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def collect_one(page, url: str, sb: SupabaseClient, run_mode: str) -> DayReport:
    """1ページ分を取得してSupabaseにupsertし、DayReportを返す(前日リンクの取得のため)。"""
    try:
        report = await scrape_report_page(page, url)
    except Exception as e:
        logger.exception("スクレイピング中にエラー: %s", url)
        sb.log_collection(None, url, status="failed", error_message=str(e), run_mode=run_mode)
        raise

    if report.report_date is None:
        logger.error("日付を特定できませんでした: %s", url)
        sb.log_collection(None, url, status="failed", error_message="date not found", run_mode=run_mode)
        return report

    if not report.rows:
        logger.warning("データ0件: %s (%s)", url, report.report_date)
        sb.log_collection(report.report_date, url, status="no_data", run_mode=run_mode)
        return report

    n = sb.upsert_day_report(report)
    sb.log_collection(report.report_date, url, status="success", rows_collected=n, run_mode=run_mode)
    logger.info("保存完了: %s件 (%s)", n, report.report_date)
    return report


async def run_daily(sb: SupabaseClient) -> None:
    playwright, browser, context, page = await new_page(headless=True)
    try:
        latest_url = await find_latest_report_url(page, TAG_URL)
        if latest_url is None:
            logger.error("最新レポートのURLが見つかりませんでした。タグページの構造が変わった可能性があります。")
            sys.exit(1)
        await collect_one(page, latest_url, sb, run_mode="daily")
    finally:
        await browser.close()
        await playwright.stop()


async def run_backfill(sb: SupabaseClient, start: date, end: date, start_url: str | None, force: bool) -> None:
    playwright, browser, context, page = await new_page(headless=True)
    try:
        current_url = start_url
        if current_url is None:
            current_url = await find_latest_report_url(page, TAG_URL)
            if current_url is None:
                logger.error("開始URLを特定できませんでした。--start-url を指定してください。")
                sys.exit(1)

        already_done = set() if force else sb.get_collected_dates(run_mode="backfill")

        visited = 0
        while current_url and visited < MAX_BACKFILL_DAYS:
            visited += 1

            report = await scrape_report_page(page, current_url)

            if report.report_date is None:
                logger.error("日付が特定できずバックフィルを継続できません: %s", current_url)
                sb.log_collection(None, current_url, status="failed", error_message="date not found", run_mode="backfill")
                break

            if report.report_date > end:
                logger.info("%s は対象期間より新しいためスキップして前日へ", report.report_date)
                current_url = report.prev_day_url
                continue

            if report.report_date < start:
                logger.info("%s は対象期間より古いため終了します", report.report_date)
                break

            if report.report_date.isoformat() in already_done:
                logger.info("%s は取得済みのためスキップ", report.report_date)
            elif not report.rows:
                logger.warning("データ0件: %s (%s)", current_url, report.report_date)
                sb.log_collection(report.report_date, current_url, status="no_data", run_mode="backfill")
            else:
                n = sb.upsert_day_report(report)
                sb.log_collection(report.report_date, current_url, status="success", rows_collected=n, run_mode="backfill")
                logger.info("保存完了: %s件 (%s)", n, report.report_date)

            if report.prev_day_url is None:
                logger.warning("「前日」リンクが見つかりませんでした。%s でバックフィルが止まります。", report.report_date)
                break

            current_url = report.prev_day_url

        if visited >= MAX_BACKFILL_DAYS:
            logger.warning("安全上限(%d日)に達したため停止しました。", MAX_BACKFILL_DAYS)

    finally:
        await browser.close()
        await playwright.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="ACT GOLD長浜 スロット台データ収集")
    sub = parser.add_subparsers(dest="mode", required=True)

    sub.add_parser("daily", help="最新1日分を取得")

    bf = sub.add_parser("backfill", help="指定期間をバックフィル")
    bf.add_argument("--start", type=parse_date, required=True, help="開始日 YYYY-MM-DD")
    bf.add_argument("--end", type=parse_date, required=True, help="終了日 YYYY-MM-DD")
    bf.add_argument("--start-url", type=str, default=None, help="遡り始める個別レポートのURL(省略時は最新から)")
    bf.add_argument("--force", action="store_true", help="取得済みの日付も再取得する")

    args = parser.parse_args()
    sb = SupabaseClient()

    if args.mode == "daily":
        asyncio.run(run_daily(sb))
    elif args.mode == "backfill":
        asyncio.run(run_backfill(sb, args.start, args.end, args.start_url, args.force))


if __name__ == "__main__":
    main()

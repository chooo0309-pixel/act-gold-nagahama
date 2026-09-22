"""
Supabase (PostgREST) への書き込みを行う薄いクライアント。

supabase-py を使わず httpx で直接REST APIを叩いている理由:
  - upsert (on_conflict) の挙動を明示的に制御したいため
  - 依存を最小限にし、GitHub Actions上でのインストールを軽くするため

必要な環境変数:
  SUPABASE_URL          例: https://xxxxx.supabase.co
  SUPABASE_SERVICE_ROLE_KEY   service_role キー (RLSを回避して書き込むため。
                               anon キーではRLSにより書き込みがブロックされる)
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from typing import Iterable

import httpx

from .scraper import DayReport, MachineRow

logger = logging.getLogger("collector.supabase_client")


class SupabaseClient:
    def __init__(self, url: str | None = None, service_role_key: str | None = None):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        self.key = service_role_key or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self._client = httpx.Client(
            base_url=f"{self.url}/rest/v1",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            timeout=30.0,
        )

    def upsert_day_report(self, report: DayReport) -> int:
        """1日分のレポートをupsertする。挿入/更新した行数を返す。"""
        if report.report_date is None:
            raise ValueError(
                f"report_date が特定できませんでした (source_url={report.source_url})。"
                " ページから日付を抽出できていない可能性があります。"
            )

        payload = [
            {
                "report_date": report.report_date.isoformat(),
                "machine_name": row.machine_name,
                "unit_number": row.unit_number,
                "diff_medals": row.diff_medals,
                "game_count": row.game_count,
                "payout_rate": row.payout_rate,
                "bb_count": row.bb_count,
                "rb_count": row.rb_count,
                "composite_denom": row.composite_denom,
                "bb_rate_denom": row.bb_rate_denom,
                "rb_rate_denom": row.rb_rate_denom,
                "source_url": report.source_url,
            }
            for row in report.rows
        ]

        if not payload:
            logger.warning("行データが0件のためupsertをスキップ: %s", report.source_url)
            return 0

        resp = self._client.post(
            "/slot_daily_data?on_conflict=report_date,machine_name,unit_number",
            json=payload,
        )
        resp.raise_for_status()
        return len(payload)

    def log_collection(
        self,
        report_date,
        source_url: str | None,
        status: str,
        rows_collected: int = 0,
        error_message: str | None = None,
        run_mode: str = "backfill",
    ) -> None:
        payload = {
            "report_date": report_date.isoformat() if report_date else None,
            "source_url": source_url,
            "status": status,
            "rows_collected": rows_collected,
            "error_message": error_message,
            "run_mode": run_mode,
        }
        resp = self._client.post(
            "/collection_log?on_conflict=report_date,run_mode",
            json=[payload],
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
        resp.raise_for_status()

    def get_collected_dates(self, run_mode: str = "backfill") -> set[str]:
        """すでに success で記録済みの report_date 一覧を取得する(重複実行を避けるため)。"""
        resp = self._client.get(
            "/collection_log",
            params={
                "select": "report_date",
                "status": "eq.success",
                "run_mode": f"eq.{run_mode}",
            },
        )
        resp.raise_for_status()
        return {row["report_date"] for row in resp.json()}

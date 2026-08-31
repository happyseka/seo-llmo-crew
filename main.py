#!/usr/bin/env python3
"""
main.py
========
SEO/LLMO記事自動化システムのコマンドラインエントリポイント。
GitHub Actionsのスケジュール実行から呼び出される想定。

使い方:
  # 翌月分の記事をまとめて作成・予約投稿（全クライアント）
  python main.py create-batch --client all

  # 先月分のアナリティクスを解析してリライト（全クライアント）
  python main.py improve --client all

  # 上記2つを通しで実行し、最後に統合の作業報告を送る（月次サイクル本体）
  python main.py monthly-cycle --client all

  # 特定クライアントだけ、対象年月を指定して実行することも可能
  python main.py monthly-cycle --client client_a --article-year 2026 --article-month 9
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.config_loader import ClientConfig, ConfigError, get_client, load_all_clients
from src.crew_article import run_monthly_article_batch
from src.crew_improve import run_monthly_improve_batch
from src.crew_report import run_work_report
from src.date_utils import month_label_ja, next_month, previous_month
from src.schemas import AnalyticsFindings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def _resolve_clients(client_arg: str) -> list[ClientConfig]:
    if client_arg == "all":
        clients = load_all_clients(active_only=True)
        if not clients:
            logger.warning("config/clients.yaml に有効なクライアントがありません。")
        return clients
    return [get_client(client_arg)]


def cmd_create_batch(args: argparse.Namespace) -> int:
    ok = True
    for client in _resolve_clients(args.client):
        try:
            articles = run_monthly_article_batch(client, year=args.article_year, month=args.article_month)
            logger.info("[%s] 記事作成バッチ完了: %d本", client.id, len(articles))
        except Exception:
            logger.exception("[%s] 記事作成バッチでエラーが発生しました", client.id)
            ok = False
    return 0 if ok else 1


def cmd_improve(args: argparse.Namespace) -> int:
    ok = True
    for client in _resolve_clients(args.client):
        try:
            findings, rewrites = run_monthly_improve_batch(
                client, year=args.improve_year, month=args.improve_month
            )
            logger.info("[%s] 記事改善バッチ完了: リライト%d件", client.id, len(rewrites))
        except Exception:
            logger.exception("[%s] 記事改善バッチでエラーが発生しました", client.id)
            ok = False
    return 0 if ok else 1


def cmd_monthly_cycle(args: argparse.Namespace) -> int:
    """記事作成バッチ → 記事改善バッチ → 統合作業報告、を通しで実行する。"""
    ok = True
    a_year, a_month = (args.article_year, args.article_month) if args.article_year else next_month()
    i_year, i_month = (args.improve_year, args.improve_month) if args.improve_year else previous_month()

    for client in _resolve_clients(args.client):
        logger.info("===== [%s] 月次サイクル開始 =====", client.id)
        articles = []
        findings = AnalyticsFindings(period_days=0, headline_summary="(未実施)")
        rewrites = []

        try:
            articles = run_monthly_article_batch(client, year=a_year, month=a_month)
        except Exception:
            logger.exception("[%s] 記事作成バッチでエラーが発生しました", client.id)
            ok = False

        try:
            findings, rewrites = run_monthly_improve_batch(client, year=i_year, month=i_month)
        except Exception:
            logger.exception("[%s] 記事改善バッチでエラーが発生しました", client.id)
            ok = False

        period_label = f"{month_label_ja(a_year, a_month)}分作成 / {month_label_ja(i_year, i_month)}分改善"
        try:
            run_work_report(client, period_label, articles, findings, rewrites)
        except Exception:
            logger.exception("[%s] 作業報告の送信でエラーが発生しました", client.id)
            ok = False

        logger.info("===== [%s] 月次サイクル終了 =====", client.id)

    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SEO/LLMO記事自動化システム")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--client", default="all", help="クライアントID（config/clients.yamlのid）。'all'で全クライアント")

    p1 = sub.add_parser("create-batch", help="翌月分の記事をまとめて作成・予約投稿する")
    add_common(p1)
    p1.add_argument("--article-year", type=int, default=None)
    p1.add_argument("--article-month", type=int, default=None)
    p1.set_defaults(func=cmd_create_batch)

    p2 = sub.add_parser("improve", help="先月分のアナリティクスを解析してリライトする")
    add_common(p2)
    p2.add_argument("--improve-year", type=int, default=None)
    p2.add_argument("--improve-month", type=int, default=None)
    p2.set_defaults(func=cmd_improve)

    p3 = sub.add_parser("monthly-cycle", help="記事作成→記事改善→作業報告を通しで実行する（月次バッチ本体）")
    add_common(p3)
    p3.add_argument("--article-year", type=int, default=None)
    p3.add_argument("--article-month", type=int, default=None)
    p3.add_argument("--improve-year", type=int, default=None)
    p3.add_argument("--improve-month", type=int, default=None)
    p3.set_defaults(func=cmd_monthly_cycle)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except ConfigError as e:
        logger.error("設定エラー: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())

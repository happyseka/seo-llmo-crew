#!/usr/bin/env python3
"""
check_setup.py
================
記事作成を始める前に、設定（.env / config/clients.yaml）が正しいかを
まとめて確認するスクリプト。GitHub Actionsの「動作確認」ワークフローから
実行される他、ローカルでも `python scripts/check_setup.py` で実行できる。

エラーがあっても途中で止めず、すべての項目を確認してから結果一覧を表示する。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config_loader import ConfigError, load_all_clients, require_env  # noqa: E402


def check_anthropic_key() -> tuple[bool, str]:
    try:
        require_env("ANTHROPIC_API_KEY")
        return True, "ANTHROPIC_API_KEY が設定されています。"
    except ConfigError as e:
        return False, str(e)


def check_smtp() -> tuple[bool, str]:
    try:
        for name in ["NOTIFY_SMTP_HOST", "NOTIFY_SMTP_PORT", "NOTIFY_SMTP_USER", "NOTIFY_SMTP_APP_PASSWORD"]:
            require_env(name)
        return True, "メール送信設定（SMTP）が揃っています。"
    except ConfigError as e:
        return False, str(e)


def check_preview_base_url() -> tuple[bool, str]:
    if os.environ.get("PREVIEW_BASE_URL"):
        return True, f"PREVIEW_BASE_URL = {os.environ['PREVIEW_BASE_URL']}"
    return False, "PREVIEW_BASE_URL が未設定です（GitHub Pagesのアドレスを設定してください）。"


def check_wordpress(client) -> tuple[bool, str]:
    try:
        from tools.wordpress_tool import test_connection

        test_connection(client)
        return True, f"[{client.id}] WordPressへの接続に成功しました。"
    except Exception as e:  # noqa: BLE001
        return False, f"[{client.id}] WordPress接続エラー: {e}"


def check_analytics(client) -> tuple[bool, str]:
    if not client.ga4_property_id and not client.gsc_site_url:
        return True, f"[{client.id}] GA4/GSCは未設定です（記事作成は可能ですが、記事改善は動作しません）。"
    try:
        from datetime import date, timedelta

        from tools.analytics_tool import get_analytics_summary

        end = date.today()
        start = end - timedelta(days=7)
        get_analytics_summary(client, start, end, period_label="疎通確認(直近7日)")
        return True, f"[{client.id}] Google Analytics / Search Console への接続に成功しました。"
    except Exception as e:  # noqa: BLE001
        return False, f"[{client.id}] アナリティクス接続エラー: {e}"


def main() -> int:
    print("=" * 60)
    print("SEO/LLMO記事自動化システム セットアップ確認")
    print("=" * 60)

    results: list[tuple[bool, str]] = []
    results.append(check_anthropic_key())
    results.append(check_smtp())
    results.append(check_preview_base_url())

    try:
        clients = load_all_clients(active_only=True)
    except ConfigError as e:
        results.append((False, f"config/clients.yaml の読み込みエラー: {e}"))
        clients = []

    if not clients:
        results.append((False, "有効なクライアントが1件もありません。config/clients.yaml を確認してください。"))

    for c in clients:
        results.append(check_wordpress(c))
        results.append(check_analytics(c))

    print()
    ok_count = 0
    for ok, message in results:
        mark = "✅" if ok else "❌"
        print(f"{mark} {message}")
        if ok:
            ok_count += 1

    print()
    print(f"結果: {ok_count} / {len(results)} 項目が正常です。")

    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

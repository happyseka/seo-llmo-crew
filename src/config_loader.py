"""
config_loader.py
=================
config/clients.yaml と .env を読み込み、コードの他の部分が使いやすい形の
Python辞書（ClientConfig）として返すモジュール。

このファイルが「設定の一元管理場所」です。他のツール・エージェントは
このモジュール経由でのみ設定・認証情報を取得します。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLIENTS_YAML_PATH = PROJECT_ROOT / "config" / "clients.yaml"
CLIENTS_YAML_EXAMPLE_PATH = PROJECT_ROOT / "config" / "clients.example.yaml"
ENV_PATH = PROJECT_ROOT / ".env"

# .envを読み込む（存在しない場合は何もしない = 実行環境の環境変数をそのまま使う）
load_dotenv(dotenv_path=ENV_PATH, override=False)


class ConfigError(RuntimeError):
    """設定ファイルや環境変数の不備を表すエラー。"""


@dataclass
class ClientConfig:
    """1クライアントサイト分の設定＋認証情報をまとめたもの。"""

    id: str
    display_name: str
    active: bool
    site_url: str
    wp_username: str
    env_prefix: str
    industry: str
    target_audience: str
    brand_tone: str
    primary_keywords: list[str]
    forbidden_topics: list[str]
    default_category: str
    post_status: str
    posts_per_week: int
    publish_weekdays: list[str]  # 例: ["mon", "wed", "fri"]
    publish_time: str  # 例: "10:00"（日本時間）
    rewrite_max_per_month: int
    notify_email: str
    ga4_property_id: str | None
    gsc_site_url: str | None
    accent_color: str | None = None  # 例: "#4A90D9"（省略時はクライアント名から自動生成）

    # 実行時に .env から解決される秘匿情報
    wp_app_password: str = field(default="", repr=False)
    google_service_account_json: str | None = field(default=None, repr=False)

    def require_wp_credentials(self) -> tuple[str, str]:
        if not self.wp_app_password:
            raise ConfigError(
                f"[{self.id}] WordPressのアプリケーションパスワードが未設定です。"
                f".env に {self.env_prefix}_WP_APP_PASSWORD を設定してください。"
            )
        return self.wp_username, self.wp_app_password


def _load_raw_yaml() -> dict[str, Any]:
    path = CLIENTS_YAML_PATH
    if not path.exists():
        raise ConfigError(
            "config/clients.yaml が見つかりません。\n"
            "config/clients.example.yaml をコピーして config/clients.yaml を作成し、"
            "クライアント情報を記入してください。"
        )
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "clients" not in data or not isinstance(data["clients"], list):
        raise ConfigError("config/clients.yaml の形式が不正です（'clients:' のリストが必要です）。")
    return data


_WEEKDAY_PRESETS: dict[int, list[str]] = {
    1: ["wed"],
    2: ["tue", "thu"],
    3: ["mon", "wed", "fri"],
    4: ["mon", "tue", "thu", "fri"],
    5: ["mon", "tue", "wed", "thu", "fri"],
}


def _default_weekdays(posts_per_week: int) -> list[str]:
    """publish_weekdaysが未指定の場合、posts_per_weekから自動で曜日を割り当てる。"""
    return _WEEKDAY_PRESETS.get(posts_per_week, ["mon", "wed", "fri"])


def _resolve_client(raw: dict[str, Any]) -> ClientConfig:
    prefix = raw.get("env_prefix")
    if not prefix:
        raise ConfigError(f"クライアント '{raw.get('id')}' に env_prefix が設定されていません。")

    wp_app_password = os.environ.get(f"{prefix}_WP_APP_PASSWORD", "")
    google_json = os.environ.get(f"{prefix}_GOOGLE_SERVICE_ACCOUNT_JSON")

    return ClientConfig(
        id=raw["id"],
        display_name=raw.get("display_name", raw["id"]),
        active=bool(raw.get("active", True)),
        site_url=raw["site_url"].rstrip("/"),
        wp_username=raw["wp_username"],
        env_prefix=prefix,
        industry=raw.get("industry", ""),
        target_audience=raw.get("target_audience", ""),
        brand_tone=raw.get("brand_tone", ""),
        primary_keywords=raw.get("primary_keywords", []) or [],
        forbidden_topics=raw.get("forbidden_topics", []) or [],
        default_category=raw.get("default_category", "コラム"),
        post_status=raw.get("post_status", "future"),
        posts_per_week=int(raw.get("posts_per_week", 3)),
        publish_weekdays=raw.get("publish_weekdays") or _default_weekdays(int(raw.get("posts_per_week", 3))),
        publish_time=raw.get("publish_time", "10:00"),
        rewrite_max_per_month=int(raw.get("rewrite_max_per_month", 3)),
        notify_email=raw.get("notify_email", ""),
        ga4_property_id=raw.get("ga4_property_id") or None,
        gsc_site_url=raw.get("gsc_site_url") or None,
        accent_color=raw.get("accent_color") or None,
        wp_app_password=wp_app_password,
        google_service_account_json=google_json,
    )


def load_all_clients(active_only: bool = True) -> list[ClientConfig]:
    """config/clients.yaml 内の全クライアントを読み込む。"""
    raw = _load_raw_yaml()
    clients = [_resolve_client(c) for c in raw["clients"]]
    if active_only:
        clients = [c for c in clients if c.active]
    return clients


def get_client(client_id: str) -> ClientConfig:
    """指定したIDのクライアント設定を1件取得する。"""
    for c in load_all_clients(active_only=False):
        if c.id == client_id:
            return c
    raise ConfigError(
        f"クライアント '{client_id}' が config/clients.yaml に見つかりません。"
    )


def require_env(name: str) -> str:
    """必須の環境変数を取得する。未設定ならわかりやすいエラーを出す。"""
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"環境変数 {name} が設定されていません。.env ファイルを確認してください。"
        )
    return value


if __name__ == "__main__":
    # 動作確認用: python -m src.config_loader
    try:
        clients = load_all_clients(active_only=False)
    except ConfigError as e:
        print(f"[設定エラー] {e}", file=sys.stderr)
        sys.exit(1)

    print(f"{len(clients)} 件のクライアントを読み込みました:\n")
    for c in clients:
        status = "有効" if c.active else "無効"
        print(f"- {c.id} ({c.display_name}) [{status}] -> {c.site_url}")

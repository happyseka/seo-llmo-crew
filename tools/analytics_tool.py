"""
analytics_tool.py
==================
Google Analytics 4 (GA4) と Google Search Console (GSC) からデータを取得し、
「アナリスト」エージェントが記事のリライト判断に使えるレポートを作るモジュール。

認証には、Googleサービスアカウントの秘密鍵（JSONファイル）を使います。
発行方法・GA4/GSCへの権限付与方法はセットアップガイドを参照してください。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from crewai.tools import tool
from google.oauth2 import service_account

from src.config_loader import ClientConfig, ConfigError

GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


class AnalyticsError(RuntimeError):
    pass


def _credentials_path(client: ClientConfig) -> Path:
    if not client.google_service_account_json:
        raise AnalyticsError(
            f"[{client.id}] Googleサービスアカウントの鍵ファイルが未設定です。"
            f".env に {client.env_prefix}_GOOGLE_SERVICE_ACCOUNT_JSON を設定してください。"
        )
    path = Path(client.google_service_account_json)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    if not path.exists():
        raise AnalyticsError(f"サービスアカウント鍵ファイルが見つかりません: {path}")
    return path


@dataclass
class PagePerformance:
    path: str
    sessions: int = 0
    engaged_sessions: int = 0
    avg_engagement_seconds: float = 0.0
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0.0
    avg_position: float = 0.0


@dataclass
class AnalyticsSummary:
    client_id: str
    period_label: str
    total_sessions: int = 0
    total_clicks: int = 0
    total_impressions: int = 0
    pages: list[PagePerformance] = field(default_factory=list)
    top_queries: list[dict] = field(default_factory=list)

    def rewrite_candidates(self, limit: int = 5) -> list[PagePerformance]:
        """
        「表示回数(impression)は多いのにクリック率(CTR)が低いページ」＝
        検索結果には出ているが読まれていない=タイトル/導入文の改善余地がある記事、
        を優先度の高いリライト候補として抽出する。
        """
        candidates = [p for p in self.pages if p.impressions >= 10]
        candidates.sort(key=lambda p: (p.ctr, -p.impressions))
        return candidates[:limit]

    def low_traffic_candidates(self, limit: int = 5) -> list[PagePerformance]:
        """セッション数が少ないページ（そもそも見つかってすらいない記事）を抽出する。"""
        candidates = sorted(self.pages, key=lambda p: p.sessions)
        return candidates[:limit]

    def to_report_text(self) -> str:
        lines = [
            f"分析期間: {self.period_label}",
            f"合計セッション数: {self.total_sessions}",
            f"検索クリック数: {self.total_clicks} / 検索表示回数: {self.total_impressions}",
            "",
            "■ リライト優先候補（表示はされているがクリック率が低いページ）",
        ]
        for p in self.rewrite_candidates():
            lines.append(
                f"  - {p.path} : 表示回数{p.impressions}回 / クリック率{p.ctr:.1%} / 平均掲載順位{p.avg_position:.1f}位"
            )
        lines.append("")
        lines.append("■ 流入が少ないページ")
        for p in self.low_traffic_candidates():
            lines.append(f"  - {p.path} : セッション数{p.sessions}")
        lines.append("")
        lines.append("■ よく検索されているキーワード（上位）")
        for q in self.top_queries[:10]:
            lines.append(
                f"  - 「{q['query']}」 表示回数{q['impressions']}回 / クリック数{q['clicks']}回 / 平均{q['position']:.1f}位"
            )
        return "\n".join(lines)


def fetch_ga4_sessions_by_page(client: ClientConfig, start_date: date, end_date: date) -> dict[str, dict]:
    """GA4から日別ではなくページパス別のセッション・エンゲージメント指標を取得する。"""
    if not client.ga4_property_id:
        raise AnalyticsError(f"[{client.id}] ga4_property_id が config/clients.yaml に設定されていません。")

    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Metric,
        RunReportRequest,
    )

    creds = service_account.Credentials.from_service_account_file(
        str(_credentials_path(client)), scopes=GA4_SCOPES
    )
    ga_client = BetaAnalyticsDataClient(credentials=creds)

    request = RunReportRequest(
        property=f"properties/{client.ga4_property_id}",
        dimensions=[Dimension(name="pagePath")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="engagedSessions"),
            Metric(name="averageSessionDuration"),
        ],
        date_ranges=[DateRange(start_date=start_date.isoformat(), end_date=end_date.isoformat())],
        limit=200,
    )

    try:
        response = ga_client.run_report(request)
    except Exception as e:  # pragma: no cover - 実行時の外部API例外をまとめて扱う
        raise AnalyticsError(f"GA4データ取得に失敗しました: {e}") from e

    result: dict[str, dict] = {}
    for row in response.rows:
        page_path = row.dimension_values[0].value
        result[page_path] = {
            "sessions": int(row.metric_values[0].value or 0),
            "engaged_sessions": int(row.metric_values[1].value or 0),
            "avg_engagement_seconds": float(row.metric_values[2].value or 0.0),
        }
    return result


def fetch_gsc_performance(client: ClientConfig, start_date: date, end_date: date) -> dict:
    """Search Consoleから、検索クエリ別・ページ別のパフォーマンスを取得する。"""
    if not client.gsc_site_url:
        raise AnalyticsError(f"[{client.id}] gsc_site_url が config/clients.yaml に設定されていません。")

    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        str(_credentials_path(client)), scopes=GSC_SCOPES
    )
    service = build("searchconsole", "v1", credentials=creds)

    start, end = start_date, end_date

    try:
        by_page = (
            service.searchanalytics()
            .query(
                siteUrl=client.gsc_site_url,
                body={
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                    "dimensions": ["page"],
                    "rowLimit": 200,
                },
            )
            .execute()
        )
        by_query = (
            service.searchanalytics()
            .query(
                siteUrl=client.gsc_site_url,
                body={
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                    "dimensions": ["query"],
                    "rowLimit": 25,
                },
            )
            .execute()
        )
    except Exception as e:  # pragma: no cover
        raise AnalyticsError(f"Search Consoleデータ取得に失敗しました: {e}") from e

    pages = {}
    for row in by_page.get("rows", []):
        page_url = row["keys"][0]
        pages[page_url] = {
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0.0),
            "position": row.get("position", 0.0),
        }

    queries = [
        {
            "query": row["keys"][0],
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0.0),
            "position": row.get("position", 0.0),
        }
        for row in by_query.get("rows", [])
    ]
    queries.sort(key=lambda q: q["impressions"], reverse=True)

    return {"pages": pages, "queries": queries}


def get_analytics_summary(
    client: ClientConfig, start_date: date, end_date: date, period_label: str | None = None
) -> AnalyticsSummary:
    """GA4 + GSC のデータを統合し、リライト判断用のサマリーを作る。"""
    label = period_label or f"{start_date.isoformat()} 〜 {end_date.isoformat()}"
    summary = AnalyticsSummary(client_id=client.id, period_label=label)

    ga4_data: dict[str, dict] = {}
    gsc_data: dict = {"pages": {}, "queries": []}

    errors = []
    try:
        ga4_data = fetch_ga4_sessions_by_page(client, start_date, end_date)
    except AnalyticsError as e:
        errors.append(str(e))
    try:
        gsc_data = fetch_gsc_performance(client, start_date, end_date)
    except AnalyticsError as e:
        errors.append(str(e))

    if errors and not ga4_data and not gsc_data["pages"]:
        raise AnalyticsError(" / ".join(errors))

    all_paths = set(ga4_data.keys()) | set(
        _strip_domain(p, client.site_url) for p in gsc_data["pages"].keys()
    )

    for path in all_paths:
        ga = ga4_data.get(path, {})
        gsc_full_url = client.site_url.rstrip("/") + path
        gsc = gsc_data["pages"].get(gsc_full_url, {})
        perf = PagePerformance(
            path=path,
            sessions=ga.get("sessions", 0),
            engaged_sessions=ga.get("engaged_sessions", 0),
            avg_engagement_seconds=ga.get("avg_engagement_seconds", 0.0),
            clicks=gsc.get("clicks", 0),
            impressions=gsc.get("impressions", 0),
            ctr=gsc.get("ctr", 0.0),
            avg_position=gsc.get("position", 0.0),
        )
        summary.pages.append(perf)

    summary.total_sessions = sum(p.sessions for p in summary.pages)
    summary.total_clicks = sum(p.clicks for p in summary.pages)
    summary.total_impressions = sum(p.impressions for p in summary.pages)
    summary.top_queries = gsc_data["queries"]

    return summary


def _strip_domain(url: str, site_url: str) -> str:
    if url.startswith(site_url):
        return url[len(site_url.rstrip("/")):] or "/"
    return url


# ---------------------------------------------------------------------
# CrewAI Agent 用ツール
# ---------------------------------------------------------------------

def build_analytics_tools(
    client: ClientConfig, start_date: date, end_date: date, period_label: str
) -> list:
    """アナリストエージェントが、指定された対象期間のアナリティクスデータを取得できるようにするツール。"""

    @tool("アナリティクスレポート取得ツール")
    def get_analytics_report_tool() -> str:
        """
        Google AnalyticsとSearch Consoleから、今回の対象期間（先月分）のサイトパフォーマンスを取得し、
        リライト優先候補・流入が少ないページ・よく検索されているキーワードをまとめたレポートを返す。
        引数は不要（対象期間はあらかじめ固定されている）。
        """
        try:
            summary = get_analytics_summary(client, start_date, end_date, period_label=period_label)
            return summary.to_report_text()
        except AnalyticsError as e:
            return f"データ取得エラー: {e}"

    return [get_analytics_report_tool]


if __name__ == "__main__":
    import sys
    from datetime import timedelta as _td

    from src.config_loader import get_client

    if len(sys.argv) < 2:
        print("使い方: python -m tools.analytics_tool <client_id>")
        sys.exit(1)

    c = get_client(sys.argv[1])
    end = date.today()
    start = end - _td(days=28)
    try:
        s = get_analytics_summary(c, start, end, period_label="直近28日間")
        print(s.to_report_text())
    except (AnalyticsError, ConfigError) as e:
        print(f"[NG] {e}")
        sys.exit(1)

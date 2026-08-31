"""
crew_improve.py
================
「記事改善バッチ」の実行本体。

先月分のアクセス解析（GA4 + Search Console）を行い、リライトすべき記事を
根拠つきで特定したうえで、実際に記事を書き直してWordPressを更新し、
「リライト報告」メールを送信する。
"""

from __future__ import annotations

import logging

from crewai import Crew, Process

from src.agents.definitions import build_analyst, build_editor, build_writer
from src.config_loader import ClientConfig
from src.date_utils import month_date_range, month_label_ja, previous_month
from src.schemas import AnalyticsFindings, RewriteResult
from src.tasks.improve_tasks import (
    build_analytics_task,
    build_rewrite_editing_task,
    build_rewrite_writing_task,
)
from tools.analytics_tool import AnalyticsError, build_analytics_tools
from tools.email_tool import EmailError, notify_rewrite_report
from tools.wordpress_tool import build_update_tool, get_post, resolve_post_by_path

logger = logging.getLogger(__name__)


def _run_analytics_analysis(client: ClientConfig, period_label: str, start_date, end_date) -> AnalyticsFindings:
    analytics_tools = build_analytics_tools(client, start_date, end_date, period_label)
    analyst = build_analyst(client, tools=analytics_tools)
    analytics_task = build_analytics_task(analyst, client, period_label=period_label)

    crew = Crew(agents=[analyst], tasks=[analytics_task], process=Process.sequential, verbose=True)
    crew.kickoff()

    findings: AnalyticsFindings | None = analytics_task.output.pydantic if analytics_task.output else None
    if findings is None:
        raise RuntimeError(
            f"[{client.id}] アナリストの出力を AnalyticsFindings として解析できませんでした。"
            f"raw出力: {analytics_task.output.raw if analytics_task.output else '(なし)'}"
        )
    return findings


def _rewrite_one(client: ClientConfig, candidate) -> tuple[RewriteResult, str] | None:
    post = resolve_post_by_path(client, candidate.page_path)
    if not post:
        logger.warning("[%s] ページパスに対応する投稿が見つかりませんでした: %s", client.id, candidate.page_path)
        return None

    post_detail = get_post(client, post["id"])
    existing_title = post_detail.get("title", {}).get("rendered", "")
    existing_content = post_detail.get("content", {}).get("rendered", "")

    writer = build_writer(client)
    update_tools = build_update_tool(client, post_detail["id"])
    editor = build_editor(client, tools=update_tools)

    writing_task = build_rewrite_writing_task(
        writer, client,
        page_path=candidate.page_path,
        reason=candidate.reason,
        suggested_change=candidate.suggested_change,
        existing_title=existing_title,
        existing_content_html=existing_content,
    )
    editing_task = build_rewrite_editing_task(
        editor, client, page_path=candidate.page_path, context=[writing_task]
    )

    crew = Crew(
        agents=[writer, editor],
        tasks=[writing_task, editing_task],
        process=Process.sequential,
        verbose=True,
    )
    crew.kickoff()

    result: RewriteResult | None = editing_task.output.pydantic if editing_task.output else None
    if result is None:
        logger.error("[%s] リライト結果の解析に失敗しました: %s", client.id, candidate.page_path)
        return None

    return RewriteResult(
        page_path=result.page_path or candidate.page_path,
        new_title=result.new_title,
        new_meta_description=result.new_meta_description,
        new_content_html=result.new_content_html,
        change_summary=result.change_summary,
        updated=result.updated,
    ), existing_title


def run_monthly_improve_batch(
    client: ClientConfig, year: int | None = None, month: int | None = None
) -> tuple[AnalyticsFindings, list[RewriteResult]]:
    """先月分のアナリティクスを解析し、必要な記事をリライトして、リライト報告メールを送る。"""
    if year is None or month is None:
        year, month = previous_month()

    period_label = f"{month_label_ja(year, month)}分"
    start_date, end_date = month_date_range(year, month)

    try:
        findings = _run_analytics_analysis(client, period_label, start_date, end_date)
    except (RuntimeError, AnalyticsError) as e:
        logger.error("[%s] アナリティクス分析に失敗しました: %s", client.id, e)
        findings = AnalyticsFindings(period_days=(end_date - start_date).days, headline_summary=f"分析エラー: {e}")

    rewrite_results: list[RewriteResult] = []
    old_titles: dict[str, str] = {}

    for candidate in findings.rewrite_candidates[: client.rewrite_max_per_month]:
        try:
            outcome = _rewrite_one(client, candidate)
        except Exception as e:  # noqa: BLE001 - バッチ全体を止めないため広く捕捉（WordPressError等を含む）
            logger.exception("[%s] リライト処理でエラーが発生しました (%s): %s", client.id, candidate.page_path, e)
            continue
        if outcome is None:
            continue
        result, old_title = outcome
        rewrite_results.append(result)
        old_titles[result.page_path] = old_title

    try:
        notify_rewrite_report(
            client_display_name=client.display_name,
            notify_email=client.notify_email,
            period_label=period_label,
            rewrites=[
                {
                    "page_path": r.page_path,
                    "old_title": old_titles.get(r.page_path, ""),
                    "new_title": r.new_title,
                    "reason": next(
                        (c.reason for c in findings.rewrite_candidates if c.page_path == r.page_path), ""
                    ),
                    "change_summary": r.change_summary,
                    "updated": r.updated,
                }
                for r in rewrite_results
            ],
        )
    except EmailError as e:
        logger.error("[%s] リライト報告メールの送信に失敗しました: %s", client.id, e)

    return findings, rewrite_results


if __name__ == "__main__":
    import sys

    from src.config_loader import get_client

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("使い方: python -m src.crew_improve <client_id> [year] [month]")
        sys.exit(1)

    client_id = sys.argv[1]
    y = int(sys.argv[2]) if len(sys.argv) > 2 else None
    m = int(sys.argv[3]) if len(sys.argv) > 3 else None
    f, results = run_monthly_improve_batch(get_client(client_id), year=y, month=m)
    print(f.model_dump_json(indent=2))
    for r in results:
        print(r.model_dump_json(indent=2))

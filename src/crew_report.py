"""
crew_report.py
===============
月次サイクル（記事作成バッチ＋記事改善バッチ）の最後に送る、統合的な
「作業報告」メールを作成・送信する。
"""

from __future__ import annotations

import logging

from crewai import Crew, Process

from src.agents.definitions import build_analyst
from src.config_loader import ClientConfig
from src.schemas import AnalyticsFindings, ArticleResult, RewriteResult, WorkReport
from src.tasks.improve_tasks import build_report_task
from tools.email_tool import build_email_tools

logger = logging.getLogger(__name__)


def _compose_context_summary(
    period_label: str,
    articles: list[ArticleResult],
    findings: AnalyticsFindings,
    rewrites: list[RewriteResult],
) -> str:
    lines = [f"【{period_label}の実施内容】", ""]

    lines.append(f"■ 新規記事作成（予約投稿）: {len(articles)}本")
    for a in articles:
        lines.append(f"  - {a.title}（公開予定: {a.scheduled_at}）")

    lines.append("")
    lines.append(f"■ アナリティクス分析結果概要: {findings.headline_summary}")

    lines.append("")
    lines.append(f"■ リライト実施: {len(rewrites)}件")
    for r in rewrites:
        status = "成功" if r.updated else "失敗"
        lines.append(f"  - {r.page_path}: {r.change_summary}（更新{status}）")

    return "\n".join(lines)


def run_work_report(
    client: ClientConfig,
    period_label: str,
    articles: list[ArticleResult],
    findings: AnalyticsFindings,
    rewrites: list[RewriteResult],
) -> WorkReport | None:
    context_summary = _compose_context_summary(period_label, articles, findings, rewrites)

    email_tools = build_email_tools(client.display_name, client.notify_email)
    analyst = build_analyst(client, tools=email_tools)
    report_task = build_report_task(analyst, client, period_label=period_label, context_summary=context_summary)

    crew = Crew(agents=[analyst], tasks=[report_task], process=Process.sequential, verbose=True)
    crew.kickoff()

    report: WorkReport | None = report_task.output.pydantic if report_task.output else None
    if report is None:
        logger.error(
            "[%s] 作業報告の解析に失敗しました。raw出力: %s",
            client.id, report_task.output.raw if report_task.output else "(なし)",
        )
    return report

"""
tasks/improve_tasks.py
=======================
記事改善クルー（アナリティクス解析 → リライト → 作業報告）のタスク定義。
"""

from __future__ import annotations

from crewai import Agent, Task

from src.config_loader import ClientConfig
from src.schemas import AnalyticsFindings, RewriteResult, WorkReport


def build_analytics_task(agent: Agent, client: ClientConfig, period_label: str) -> Task:
    return Task(
        description=(
            f"『アナリティクスレポート取得ツール』を使って、{client.display_name}のサイトの"
            f"{period_label}のアクセス状況を取得・分析してください。\n\n"
            "分析の観点:\n"
            "1. 検索結果に表示されている（表示回数が多い）のに、クリック率が低いページ"
            "　→ タイトルや説明文が魅力的でない可能性が高く、最優先のリライト候補。\n"
            "2. セッション数が極端に少ないページ　→ そもそも検索順位が低い可能性。\n"
            "3. 全体の傾向（増えているか減っているか、よく検索されているキーワード）。\n\n"
            f"最大{client.rewrite_max_per_month}件まで、具体的な数値を根拠にしたリライト候補を"
            "優先順位付きで挙げてください。改善の余地がなければ無理に候補を挙げなくてよい。"
        ),
        expected_output=(
            "AnalyticsFindingsスキーマに従ったJSON。rewrite_candidatesの各項目には、"
            "page_path（サイト内パス。例: /skincare/dry-order/）、reason（数値を含む根拠）、"
            "priority、suggested_change を必ず含めること。"
        ),
        agent=agent,
        output_pydantic=AnalyticsFindings,
    )


def build_rewrite_writing_task(
    agent: Agent,
    client: ClientConfig,
    page_path: str,
    reason: str,
    suggested_change: str,
    existing_title: str,
    existing_content_html: str,
) -> Task:
    return Task(
        description=(
            f"以下の既存記事を、アナリストの分析結果に基づいてリライトしてください。\n\n"
            f"対象ページ: {page_path}\n"
            f"リライトすべき理由（根拠）: {reason}\n"
            f"提案された改善方針: {suggested_change}\n\n"
            f"現在のタイトル: {existing_title}\n"
            f"現在の本文（HTML）:\n{existing_content_html[:6000]}\n\n"
            "作業ルール:\n"
            "1. 記事の骨子（読者に伝えたい結論）は保ちつつ、指摘された弱点を直接改善する。\n"
            "2. タイトルを改善する場合は、検索意図により合致し、クリックしたくなる具体性を持たせる。\n"
            f"3. ブランドトーン「{client.brand_tone}」を守る。\n"
            "4. 本文はHTML形式（<h2>/<h3>/<p>）で、そのままWordPressに上書きできる完全な形にする。\n"
            f"5. 次のトピックには触れないこと: {', '.join(client.forbidden_topics) or '特になし'}\n"
        ),
        expected_output=(
            "リライト後の記事タイトル・本文HTML全文・120字前後のメタディスクリプションを含むテキスト。"
        ),
        agent=agent,
    )


def build_rewrite_editing_task(
    agent: Agent,
    client: ClientConfig,
    page_path: str,
    context: list[Task],
) -> Task:
    return Task(
        description=(
            "ライターがリライトした内容を推敲し、最終化したうえで、"
            "『WordPress記事更新ツール』を使って対象記事を実際に更新してください。\n\n"
            f"対象ページ: {page_path}\n\n"
            "手順:\n"
            "1. 誤字脱字・ブランドガイドライン違反がないか確認し、必要なら修正する。\n"
            "2. 更新ツールを呼び出し、new_title と new_content_html を渡して実際にWordPressを更新する。\n"
            "3. 更新ツールの呼び出し結果を必ず確認し、成功したかどうかを最終出力に反映する。\n"
        ),
        expected_output=(
            "RewriteResultスキーマに従ったJSON。page_path, new_title, new_meta_description, "
            "new_content_html（更新した本文全文HTML）, change_summary（変更点の要約）, "
            "updated（更新ツールが成功したら true、失敗したら false）をすべて埋めること。"
        ),
        agent=agent,
        context=context,
        output_pydantic=RewriteResult,
    )


def build_report_task(
    agent: Agent,
    client: ClientConfig,
    period_label: str,
    context_summary: str,
) -> Task:
    return Task(
        description=(
            f"今回（{period_label}）の作業内容をまとめ、作業報告メールを送信してください。\n\n"
            f"今回実施した内容の記録:\n{context_summary}\n\n"
            "報告に含めるべき内容:\n"
            "1. 実施したこと（新規記事の作成本数・リライトした記事とその内容）\n"
            "2. その判断の根拠（アナリティクスの具体的な数値）\n"
            "3. 今後の方針・次回予定していること\n\n"
            "手順:\n"
            "1. まず WorkReport スキーマに沿った内容を整理する。\n"
            "2. 次に『作業報告メール送信ツール』を使って、整理した内容をメールで送信する"
            "（件名は簡潔に、本文は非エンジニアにも分かりやすい言葉で）。\n"
        ),
        expected_output=(
            "WorkReportスキーマに従ったJSON（period_label, what_was_done, evidence, next_actions）。"
            "メール送信ツールの呼び出しも必ず完了させること。"
        ),
        agent=agent,
        output_pydantic=WorkReport,
    )

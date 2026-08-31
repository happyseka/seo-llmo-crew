"""
crew_article.py
================
「記事作成バッチ」の実行本体。

月末に実行し、翌月分の記事をまとめて作成する:
  リサーチ → 企画 → 執筆 → 推敲 → 挿絵・アイキャッチ作成
  → 外部確認用プレビューリンク発行 → WordPressへ予約投稿設定

すべての記事を予約投稿し終えたら、日付・タイトル・確認用リンクの一覧を
「下書き＆予約投稿報告」として1通のメールにまとめて送信する。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from crewai import Crew, Process

from src.agents.definitions import build_editor, build_researcher, build_writer
from src.config_loader import ClientConfig
from src.date_utils import compute_publish_datetimes, format_jst, month_label_ja, next_month
from src.schemas import ArticleResult
from src.tasks.article_tasks import build_editing_task, build_research_task, build_writing_task
from tools.email_tool import EmailError, notify_batch_scheduled
from tools.image_tool import build_image_tools
from tools.preview_tool import build_preview_tools
from tools.wordpress_tool import build_research_tools, build_wordpress_tools

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"


def run_single_article(client: ClientConfig, scheduled_at: datetime, topic_hint: str = "") -> ArticleResult:
    """1本分の記事を、リサーチ〜予約投稿・プレビュー発行まで通しで作成する。"""

    client_output_dir = OUTPUT_DIR / client.id / "images"
    client_output_dir.mkdir(parents=True, exist_ok=True)

    research_tools = build_research_tools(client)
    image_tools = build_image_tools(
        client_display_name=client.display_name,
        output_dir=str(client_output_dir),
        accent_color=client.accent_color,
    )
    wp_tools = build_wordpress_tools(client)
    preview_tools = build_preview_tools(client.id)

    researcher = build_researcher(client, tools=research_tools)
    writer = build_writer(client)
    editor = build_editor(client, tools=image_tools + wp_tools + preview_tools)

    research_task = build_research_task(researcher, client, topic_hint=topic_hint)
    writing_task = build_writing_task(writer, client, context=[research_task])
    editing_task = build_editing_task(
        editor,
        client,
        context=[research_task, writing_task],
        publish_datetime_iso=scheduled_at.strftime("%Y-%m-%dT%H:%M:%S"),
        scheduled_at_label=format_jst(scheduled_at),
    )

    crew = Crew(
        agents=[researcher, writer, editor],
        tasks=[research_task, writing_task, editing_task],
        process=Process.sequential,
        verbose=True,
    )
    crew.kickoff()

    article: ArticleResult | None = editing_task.output.pydantic if editing_task.output else None
    if article is None:
        raise RuntimeError(
            f"[{client.id}] 編集者エージェントの出力を ArticleResult として解析できませんでした。"
            f"raw出力: {editing_task.output.raw if editing_task.output else '(なし)'}"
        )
    return article


def run_monthly_article_batch(
    client: ClientConfig, year: int | None = None, month: int | None = None
) -> list[ArticleResult]:
    """
    翌月分（year/month指定がなければ実行時点の翌月）の記事をまとめて作成し、
    それぞれ予約投稿として登録したうえで、バッチ報告メールを1通送信する。
    """
    if year is None or month is None:
        year, month = next_month()

    schedule = compute_publish_datetimes(year, month, client.publish_weekdays, client.publish_time)
    period_label = month_label_ja(year, month)
    logger.info("[%s] %s分の記事を%d本作成します（%s）", client.id, period_label, len(schedule), client.publish_weekdays)

    articles: list[ArticleResult] = []
    recent_titles: list[str] = []

    for i, scheduled_at in enumerate(schedule, 1):
        hint = ""
        if recent_titles:
            hint = "（今回のバッチで既に企画した以下のテーマとは重複させないこと: " + " / ".join(recent_titles) + "）"
        logger.info("[%s] %d/%d本目を作成中... 予定日時=%s", client.id, i, len(schedule), format_jst(scheduled_at))
        try:
            article = run_single_article(client, scheduled_at, topic_hint=hint)
            articles.append(article)
            recent_titles.append(article.title)
        except Exception:
            logger.exception("[%s] %d本目の記事作成に失敗しました（予定日時=%s）", client.id, i, format_jst(scheduled_at))

    try:
        notify_batch_scheduled(
            client_display_name=client.display_name,
            notify_email=client.notify_email,
            period_label=period_label,
            articles=[
                {
                    "scheduled_at_label": a.scheduled_at,
                    "title": a.title,
                    "preview_url": a.preview_url,
                    "status": a.status,
                }
                for a in articles
            ],
        )
    except EmailError as e:
        logger.error("[%s] 予約投稿報告メールの送信に失敗しました: %s", client.id, e)

    return articles


if __name__ == "__main__":
    import sys

    from src.config_loader import get_client

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("使い方: python -m src.crew_article <client_id> [year] [month]")
        sys.exit(1)

    client_id = sys.argv[1]
    y = int(sys.argv[2]) if len(sys.argv) > 2 else None
    m = int(sys.argv[3]) if len(sys.argv) > 3 else None
    results = run_monthly_article_batch(get_client(client_id), year=y, month=m)
    for r in results:
        print(r.model_dump_json(indent=2, exclude_none=False))

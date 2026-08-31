"""
tasks/article_tasks.py
=======================
記事作成クルー（リサーチ → 企画 → 執筆 → 推敲 → 挿絵・アイキャッチ作成 → 公開）の
各ステップをCrewAIのTaskとして定義する。
"""

from __future__ import annotations

from crewai import Agent, Task

from src.config_loader import ClientConfig
from src.schemas import ArticleResult


def build_research_task(agent: Agent, client: ClientConfig, topic_hint: str = "") -> Task:
    keywords = "、".join(client.primary_keywords) or "（クライアントの業種に関連する一般的なキーワード）"
    topic_line = f"今回は特に次のテーマを優先的に検討してください: {topic_hint}\n" if topic_hint else ""

    return Task(
        description=(
            f"{client.display_name}（業種: {client.industry}）のオウンドメディア向けに、次の新しい記事の"
            "企画を1つ作成してください。\n\n"
            f"対象読者: {client.target_audience}\n"
            f"軸となるキーワード候補: {keywords}\n"
            f"{topic_line}\n"
            "手順:\n"
            "1. まず『既存記事タイトル一覧取得ツール』で既存記事を確認し、テーマが重複しないようにする。\n"
            "2. 読者が本当に知りたいであろう検索意図を1つ具体的に定める。\n"
            "3. 記事タイトル案（32文字前後、数字や具体性を含める）を1つ決める。\n"
            "4. 見出し構成案（h2・h3レベル、4〜6セクション程度）を、各見出しで何を書くかの要点付きで作成する。\n"
            "5. AI検索エンジン（LLMO対策）にも引用されやすいよう、各セクションで『結論を最初に一文で言い切る』構成にする。\n\n"
            f"禁止事項: {', '.join(client.forbidden_topics) or '特になし'}\n"
        ),
        expected_output=(
            "以下を含む企画書（日本語のテキスト）:\n"
            "- 記事タイトル案\n"
            "- 検索意図（想定読者が抱えている悩み・知りたいこと）\n"
            "- 見出し構成（h2/h3と各セクションの要点）\n"
            "- 使用を検討するキーワード\n"
        ),
        agent=agent,
    )


def build_writing_task(agent: Agent, client: ClientConfig, context: list[Task]) -> Task:
    return Task(
        description=(
            "リサーチャーが作成した企画書に基づき、記事本文を執筆してください。\n\n"
            f"ブランドトーン: {client.brand_tone}\n"
            "執筆ルール:\n"
            "1. 企画書の見出し構成に沿って、HTML形式で本文を書く（<h2>、<h3>、<p>タグを使用。"
            "装飾は最小限でよい。<script>等は使わない）。\n"
            "2. 各見出しの冒頭で結論を一文で述べてから、理由・具体例を続ける（LLMOを意識した『結論ファースト』構成）。\n"
            "3. 記事全体で2000〜3200文字程度を目安にする。\n"
            "4. 導入文（リード文）で、読者の悩みへの共感と、この記事を読むと何が分かるかを簡潔に示す。\n"
            "5. まとめセクションを最後に設け、要点を箇条書き（<ul><li>）で振り返る。\n"
            f"6. 次のトピックには触れないこと: {', '.join(client.forbidden_topics) or '特になし'}\n"
        ),
        expected_output="<h2>等のタグを含む、そのままWordPressに投稿できる記事本文のHTML。",
        agent=agent,
        context=context,
    )


def build_editing_task(
    agent: Agent,
    client: ClientConfig,
    context: list[Task],
    publish_datetime_iso: str,
    scheduled_at_label: str,
) -> Task:
    tags_hint = "、".join(client.primary_keywords[:5])
    return Task(
        description=(
            "ライターが書いた記事本文を推敲し、最終化したうえで、画像を生成し、"
            "WordPressに『予約投稿』として登録し、外部確認用のプレビューリンクを発行してください。\n\n"
            "手順:\n"
            "1. 誤字脱字、論理の飛躍、ブランドガイドライン違反、誇大・断定的すぎる表現がないか確認し、"
            "問題があれば自分で修正する。\n"
            "2. SEO/LLMO観点で、記事タイトルを32文字前後に調整する（結論・具体性・数字を意識）。\n"
            "3. 120字前後のメタディスクリプション（検索結果に表示される要約文）を作成する。\n"
            "4. 『アイキャッチ画像生成ツール』を使って、最終タイトルからアイキャッチ画像を生成する。\n"
            "5. 記事が長い場合は『挿絵生成ツール』で1〜2枚、本文中に挟む挿絵も生成し、"
            "該当箇所に <img src=\"（生成された画像パス）\" alt=\"...\"> を挿入する（任意。無理に入れなくてもよい）。\n"
            f"6. 『外部確認用プレビューページ生成ツール』を使って、確認用リンクを発行する"
            f"（scheduled_at_labelには必ず \"{scheduled_at_label}\" をそのまま渡すこと）。\n"
            "7. 完成した記事本文とアイキャッチ画像を使って『WordPress予約投稿ツール』を呼び出し、"
            f"以下の内容で予約投稿する。\n"
            f"   - publish_datetime_iso には必ず \"{publish_datetime_iso}\" をそのまま渡すこと\n"
            f"   - カテゴリ: {client.default_category}\n"
            f"   - タグの参考例: {tags_hint}\n"
            "8. 予約投稿ツールとプレビューツールの結果（投稿ID・URL・ステータス・プレビューURL）を"
            "必ず最終出力に含める。\n"
        ),
        expected_output=(
            "ArticleResultスキーマに従ったJSON。title, meta_description, category, tags, summary, "
            "wordpress_post_id, wordpress_url, status, scheduled_at, preview_url のすべてを埋めること。"
            "wordpress_post_idとpreview_urlは各ツールの実行結果から得た実際の値を使うこと（推測しない）。"
            f"scheduled_atには \"{publish_datetime_iso}\" を入れること。"
        ),
        agent=agent,
        context=context,
        output_pydantic=ArticleResult,
    )

"""
schemas.py
==========
CrewAIの各エージェントに「この形式で出力して」と指定するためのPydanticモデル。
構造化出力を使うことで、LLMの自由文からの解析ミスを防ぎ、後続の自動処理
（メール送信・WordPress更新など）を確実に行えるようにする。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ArticleResult(BaseModel):
    """記事作成クルーの最終成果物（公開処理後の結果）。"""

    title: str = Field(description="最終的な記事タイトル")
    meta_description: str = Field(description="120字前後のメタディスクリプション（検索結果に表示される要約文）")
    category: str = Field(description="使用したカテゴリ名")
    tags: list[str] = Field(default_factory=list, description="使用したタグの一覧")
    summary: str = Field(description="記事の要点を3〜4行で説明した社内向けサマリー")
    wordpress_post_id: int = Field(default=0, description="予約投稿されたWordPressの投稿ID（未取得なら0）")
    wordpress_url: str = Field(default="", description="記事の（公開後の）URL")
    status: str = Field(default="future", description="future(予約投稿) または draft")
    scheduled_at: str = Field(default="", description="予約公開日時（例: 2026-09-02T10:00:00+09:00）")
    preview_url: str = Field(default="", description="WordPressにログインしていなくても確認できる外部プレビューURL")


class RewriteCandidate(BaseModel):
    """アナリストが特定した、改善（リライト）すべき記事の候補。"""

    page_path: str = Field(description="対象ページのパス（例: /skincare/dry-skin-order/）")
    reason: str = Field(description="なぜこの記事をリライトすべきかの根拠（数値を含めて具体的に）")
    priority: int = Field(description="優先度。1が最も高い")
    suggested_change: str = Field(description="具体的にどう変更すべきかの提案（タイトル改善／内容追加など）")


class AnalyticsFindings(BaseModel):
    """アナリティクス解析結果全体。"""

    period_days: int
    headline_summary: str = Field(description="全体傾向を2〜3行で説明")
    rewrite_candidates: list[RewriteCandidate] = Field(default_factory=list)


class RewriteResult(BaseModel):
    """1記事分のリライト結果。"""

    page_path: str
    new_title: str
    new_meta_description: str
    new_content_html: str = Field(description="リライト後の本文全文（HTML）")
    change_summary: str = Field(description="今回どこをどう直したかの説明（根拠つき）")
    updated: bool = Field(default=False, description="WordPress側の更新に成功したか")


class WorkReport(BaseModel):
    """作業報告メールの本文となる構造化レポート。"""

    period_label: str = Field(description="対象期間の表現（例: 2026年8月第4週）")
    what_was_done: str = Field(description="実施した作業内容（記事作成◯本、リライト◯本など）")
    evidence: str = Field(description="判断の根拠となったデータ・数値")
    next_actions: str = Field(description="今後の方針・次回やる予定のこと")

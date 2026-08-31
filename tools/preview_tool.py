"""
preview_tool.py
================
予約投稿する記事を、WordPressにログインしていない第三者（クライアント等）でも
確認できる「外部確認用リンク」として、静的HTMLプレビューページを生成するモジュール。

生成したファイルは docs/previews/<client_id>/<slug>.html に保存し、
GitHub Pages（リポジトリの /docs フォルダを公開する無料機能）経由で
"{PREVIEW_BASE_URL}/previews/<client_id>/<slug>.html" として公開する。
GitHub Pagesの有効化方法はセットアップガイドを参照。
"""

from __future__ import annotations

import html
import os
import re
import unicodedata
from pathlib import Path

from crewai.tools import tool

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PREVIEW_ROOT_DIR = PROJECT_ROOT / "docs" / "previews"


def slugify(text: str, max_len: int = 60) -> str:
    """タイトル等から、URLに使える安全なスラッグを作る。"""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[^\w\-]+", "-", text, flags=re.UNICODE).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return (text or "article")[:max_len]


PREVIEW_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>{title} ｜ 確認用プレビュー</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", sans-serif;
          max-width: 760px; margin: 0 auto; padding: 24px; line-height: 1.85; color: #222; background: #fafafa; }}
  .preview-banner {{ background: #fff3cd; border: 1px solid #ffe08a; color: #8a6d1a; padding: 12px 16px;
                      border-radius: 8px; margin-bottom: 24px; font-size: 14px; }}
  .meta {{ color: #666; font-size: 14px; margin-bottom: 8px; }}
  img.eyecatch {{ width: 100%; height: auto; border-radius: 8px; margin: 16px 0; }}
  h1 {{ font-size: 28px; line-height: 1.4; margin-bottom: 4px; }}
  h2 {{ font-size: 22px; margin-top: 32px; border-left: 6px solid #4A90D9; padding-left: 10px; }}
  h3 {{ font-size: 18px; margin-top: 24px; }}
  article img {{ max-width: 100%; height: auto; border-radius: 8px; }}
  .article-body {{ background: #fff; padding: 24px; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }}
</style>
</head>
<body>
  <div class="preview-banner">
    これは公開前の確認用プレビューです（検索エンジンには登録されません）。<br>
    予約公開日時: {scheduled_at}
  </div>
  <div class="meta">カテゴリ: {category} ｜ 想定メタディスクリプション: {meta_description}</div>
  <h1>{title}</h1>
  {eyecatch_html}
  <div class="article-body">
    <article>
{content}
    </article>
  </div>
</body>
</html>
"""


def generate_preview_page(
    client_id: str,
    title: str,
    content_html: str,
    scheduled_at_label: str,
    category: str = "",
    meta_description: str = "",
    eyecatch_data_uri: str = "",
) -> tuple[str, str]:
    """
    静的な確認用プレビューページを生成する。

    Returns:
        (ローカルファイルパス, 想定される公開URLの相対パス "previews/<client_id>/<slug>.html")
    """
    slug = slugify(title)
    out_dir = PREVIEW_ROOT_DIR / client_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}.html"

    eyecatch_html = f'<img class="eyecatch" src="{eyecatch_data_uri}" alt="{html.escape(title)}">' if eyecatch_data_uri else ""

    page = PREVIEW_TEMPLATE.format(
        title=html.escape(title),
        scheduled_at=html.escape(scheduled_at_label),
        category=html.escape(category or "未設定"),
        meta_description=html.escape(meta_description or ""),
        eyecatch_html=eyecatch_html,
        content=content_html,
    )
    out_path.write_text(page, encoding="utf-8")

    relative_url_path = f"previews/{client_id}/{slug}.html"
    return str(out_path), relative_url_path


def _image_to_data_uri(image_path: str) -> str:
    import base64
    import mimetypes

    p = Path(image_path)
    if not p.exists():
        return ""
    mime, _ = mimetypes.guess_type(str(p))
    mime = mime or "image/png"
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def build_preview_url(relative_path: str) -> str:
    base = os.environ.get("PREVIEW_BASE_URL", "").rstrip("/")
    if not base:
        return f"(PREVIEW_BASE_URLが未設定のため、リポジトリ内の docs/{relative_path} を直接ご確認ください)"
    return f"{base}/{relative_path}"


# ---------------------------------------------------------------------
# CrewAI Agent 用ツール
# ---------------------------------------------------------------------

def build_preview_tools(client_id: str) -> list:
    @tool("外部確認用プレビューページ生成ツール")
    def generate_preview_tool(
        title: str,
        content_html: str,
        scheduled_at_label: str,
        category: str = "",
        meta_description: str = "",
        eyecatch_image_path: str = "",
    ) -> str:
        """
        完成した記事のプレビューページを静的HTMLとして生成し、WordPressにログインしていなくても
        閲覧できる外部確認用URLを返す。予約投稿の直前に必ず呼び出すこと。
        引数:
          title: 記事タイトル
          content_html: 本文HTML
          scheduled_at_label: 予約公開日時の表示用文字列（例: "2026-09-02(水) 10:00"）
          category: カテゴリ名
          meta_description: メタディスクリプション
          eyecatch_image_path: アイキャッチ画像のローカルファイルパス（あれば埋め込む）
        戻り値: 外部確認用URL
        """
        data_uri = _image_to_data_uri(eyecatch_image_path) if eyecatch_image_path else ""
        _, rel_path = generate_preview_page(
            client_id, title, content_html, scheduled_at_label,
            category=category, meta_description=meta_description, eyecatch_data_uri=data_uri,
        )
        return build_preview_url(rel_path)

    return [generate_preview_tool]

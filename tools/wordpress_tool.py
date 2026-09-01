"""
wordpress_tool.py
==================
WordPress REST API（アプリケーションパスワード認証）を使って、
記事の新規投稿・更新・画像アップロードを行うモジュール。

- 素のPython関数（publish_post, upload_media, update_post, get_post など）
  → main.py など、エージェントを介さない確実な処理から直接呼び出す用
- build_wordpress_tools(client)
  → CrewAIのAgentにアタッチできる Tool のリストを返す
    （編集者エージェントが「公開して」と判断したときに自律的に呼び出せる）

WordPress側の準備（ユーザーのアプリケーションパスワード発行）は
セットアップガイドを参照してください。
"""

from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from crewai.tools import tool

from src.config_loader import ClientConfig, ConfigError

TIMEOUT = 30


class WordPressError(RuntimeError):
    pass


def _api_base(client: ClientConfig) -> str:
    return f"{client.site_url}/wp-json/wp/v2"


def _auth(client: ClientConfig) -> tuple[str, str]:
    return client.require_wp_credentials()


def _get_or_create_term(client: ClientConfig, taxonomy: str, name: str) -> int:
    """カテゴリ／タグを名前で検索し、無ければ新規作成してIDを返す。"""
    if not name:
        raise WordPressError("空の名前でタームは作成できません。")
    base = _api_base(client)
    auth = _auth(client)

    resp = requests.get(
        f"{base}/{taxonomy}", params={"search": name}, auth=auth, timeout=TIMEOUT
    )
    resp.raise_for_status()
    for term in resp.json():
        if term.get("name") == name:
            return term["id"]

    resp = requests.post(
        f"{base}/{taxonomy}", json={"name": name}, auth=auth, timeout=TIMEOUT
    )
    if resp.status_code not in (200, 201):
        raise WordPressError(f"タームの作成に失敗しました ({taxonomy}='{name}'): {resp.status_code} {resp.text[:300]}")
    return resp.json()["id"]


def upload_media(client: ClientConfig, file_path: str, alt_text: str = "") -> dict[str, Any]:
    """
    画像ファイルをWordPressのメディアライブラリにアップロードする。

    Returns: {"id": メディアID, "source_url": 画像URL}
    """
    path = Path(file_path)
    if not path.exists():
        raise WordPressError(f"アップロード対象の画像が見つかりません: {file_path}")

    mime_type, _ = mimetypes.guess_type(str(path))
    mime_type = mime_type or "image/png"

    base = _api_base(client)
    auth = _auth(client)
    headers = {
        "Content-Disposition": f'attachment; filename="{path.name}"',
        "Content-Type": mime_type,
    }
    with open(path, "rb") as f:
        resp = requests.post(
            f"{base}/media", headers=headers, data=f.read(), auth=auth, timeout=TIMEOUT
        )
    if resp.status_code not in (200, 201):
        raise WordPressError(f"画像アップロードに失敗しました: {resp.status_code} {resp.text[:300]}")

    media = resp.json()
    media_id = media["id"]

    if alt_text:
        requests.post(
            f"{base}/media/{media_id}",
            json={"alt_text": alt_text},
            auth=auth,
            timeout=TIMEOUT,
        )

    return {"id": media_id, "source_url": media.get("source_url", "")}


def publish_post(
    client: ClientConfig,
    title: str,
    html_content: str,
    category: str | None = None,
    tags: list[str] | None = None,
    featured_image_path: str | None = None,
    status: str | None = None,
    excerpt: str | None = None,
    meta_description: str | None = None,
    publish_datetime: datetime | None = None,
) -> dict[str, Any]:
    """
    新規記事をWordPressに投稿する。
    publish_datetime を指定すると、その日時（タイムゾーン付き）でstatus="future"の
    予約投稿として登録される（statusを明示的に渡した場合はそちらを優先）。

    Returns: {"id": 投稿ID, "link": 記事URL, "status": 投稿ステータス, "scheduled_at": ISO文字列 or None}
    """
    base = _api_base(client)
    auth = _auth(client)

    resolved_status = status or (("future" if publish_datetime else None)) or client.post_status
    payload: dict[str, Any] = {
        "title": title,
        "content": html_content,
        "status": resolved_status,
    }
    if publish_datetime is not None:
        # date_gmtで指定すればWordPress側のタイムゾーン設定に依存せず正確に予約できる
        from datetime import timezone as _tz

        dt_utc = publish_datetime.astimezone(_tz.utc) if publish_datetime.tzinfo else publish_datetime
        payload["date_gmt"] = dt_utc.strftime("%Y-%m-%dT%H:%M:%S")
    if excerpt:
        payload["excerpt"] = excerpt

    if category or client.default_category:
        cat_name = category or client.default_category
        payload["categories"] = [_get_or_create_term(client, "categories", cat_name)]

    if tags:
        payload["tags"] = [_get_or_create_term(client, "tags", t) for t in tags if t.strip()]

    featured_media_id = None
    if featured_image_path:
        media = upload_media(client, featured_image_path, alt_text=title)
        featured_media_id = media["id"]
        payload["featured_media"] = featured_media_id

    resp = requests.post(f"{base}/posts", json=payload, auth=auth, timeout=TIMEOUT)
    if resp.status_code not in (200, 201):
        raise WordPressError(f"記事投稿に失敗しました: {resp.status_code} {resp.text[:500]}")

    post = resp.json()

    # Yoast SEO / RankMath 等がある場合のメタディスクリプション設定はプラグイン依存のため
    # ここでは行わず、meta_descriptionは戻り値に含めるだけに留める（本文冒頭に含める運用を推奨）。

    return {
        "id": post["id"],
        "link": post.get("link", ""),
        "status": post.get("status", ""),
        "featured_media_id": featured_media_id,
        "meta_description": meta_description,
        "scheduled_at": post.get("date") if publish_datetime is not None else None,
    }


def update_post(client: ClientConfig, post_id: int, **fields: Any) -> dict[str, Any]:
    """
    既存記事を更新する（リライト用）。
    fields には title / content / status / categories / tags などをそのまま渡せる。
    """
    base = _api_base(client)
    auth = _auth(client)
    resp = requests.post(f"{base}/posts/{post_id}", json=fields, auth=auth, timeout=TIMEOUT)
    if resp.status_code not in (200, 201):
        raise WordPressError(f"記事更新に失敗しました (id={post_id}): {resp.status_code} {resp.text[:500]}")
    post = resp.json()
    return {"id": post["id"], "link": post.get("link", ""), "status": post.get("status", "")}


def get_post(client: ClientConfig, post_id: int) -> dict[str, Any]:
    base = _api_base(client)
    auth = _auth(client)
    resp = requests.get(f"{base}/posts/{post_id}", auth=auth, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def list_recent_posts(client: ClientConfig, per_page: int = 20) -> list[dict[str, Any]]:
    base = _api_base(client)
    auth = _auth(client)
    resp = requests.get(
        f"{base}/posts",
        params={"per_page": per_page, "orderby": "date", "order": "desc"},
        auth=auth,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_recent_titles(client: ClientConfig, count: int = 15) -> list[str]:
    """直近の投稿タイトル一覧を取得する（リサーチャーが話題の重複を避けるために使う）。"""
    posts = list_recent_posts(client, per_page=count)
    return [p.get("title", {}).get("rendered", "") for p in posts]


def resolve_post_by_path(client: ClientConfig, page_path: str) -> dict[str, Any] | None:
    """
    アナリティクス上のページパス（例: /skincare/dry-order/）から、対応するWordPress投稿を検索する。
    スラッグ（URLの末尾部分）で検索するため、パーマリンク構造によっては見つからない場合がある。
    """
    slug = page_path.strip("/").split("/")[-1]
    if not slug:
        return None
    base = _api_base(client)
    auth = _auth(client)
    resp = requests.get(f"{base}/posts", params={"slug": slug}, auth=auth, timeout=TIMEOUT)
    resp.raise_for_status()
    results = resp.json()
    return results[0] if results else None


def test_connection(client: ClientConfig) -> bool:
    """認証情報が正しくWordPressに接続できるか確認する（セットアップ確認用）。"""
    base = _api_base(client)
    auth = _auth(client)
    resp = requests.get(f"{base}/users/me", auth=auth, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise WordPressError(
            f"WordPressへの接続に失敗しました（{resp.status_code}）。"
            f"ユーザー名とアプリケーションパスワードを確認してください。詳細: {resp.text[:300]}"
        )
    return True


# ---------------------------------------------------------------------
# CrewAI Agent 用ツール（クライアントごとにバインドして生成する）
# ---------------------------------------------------------------------

def build_wordpress_tools(client: ClientConfig) -> list:
    """
    指定クライアントの認証情報にひも付いたCrewAI Toolのリストを作る。
    編集者エージェントにアタッチすることで、エージェントが自律的に
    「画像をアップロードして」「記事を公開して」と判断・実行できるようになる。
    """

    @tool("schedule_wordpress_post")
    def schedule_wordpress_post_tool(
        title: str,
        html_content: str,
        publish_datetime_iso: str,
        category: str = "",
        tags_csv: str = "",
        featured_image_path: str = "",
    ) -> str:
        """
        完成した記事をWordPressに「予約投稿」として登録する（指定した日本時間の日時に自動公開される）。
        引数:
          title: 記事タイトル
          html_content: 本文のHTML（見出しは<h2>/<h3>、段落は<p>タグを使うこと）
          publish_datetime_iso: 予約公開する日時。タスク指示で与えられた日時をそのまま
                                 "YYYY-MM-DDTHH:MM:SS" 形式（日本時間）で指定すること。
          category: カテゴリ名（空なら既定カテゴリを使用）
          tags_csv: カンマ区切りのタグ一覧（例: "毛穴ケア,スキンケア,美容"）
          featured_image_path: アイキャッチ画像のローカルファイルパス（あれば指定）
        戻り値: 投稿結果を説明する文字列（投稿IDと予約公開日時を含む）
        """
        try:
            from src.date_utils import JST

            dt = datetime.fromisoformat(publish_datetime_iso).replace(tzinfo=JST)
            tags = [t.strip() for t in tags_csv.split(",")] if tags_csv else []
            result = publish_post(
                client,
                title=title,
                html_content=html_content,
                category=category or None,
                tags=tags,
                featured_image_path=featured_image_path or None,
                publish_datetime=dt,
            )
            return (
                f"予約投稿成功: id={result['id']}, status={result['status']}, "
                f"公開予定={publish_datetime_iso}(JST), url={result['link']}"
            )
        except (WordPressError, ConfigError, ValueError) as e:
            return f"予約投稿失敗: {e}"

    return [schedule_wordpress_post_tool]


def build_update_tool(client: ClientConfig, post_id: int) -> list:
    """特定の投稿ID専用の更新ツール（記事改善／リライト用に、対象記事を固定してバインドする）。"""

    @tool("update_wordpress_post")
    def update_wordpress_post_tool(new_title: str, new_content_html: str) -> str:
        """
        リライトした内容で、対象のWordPress記事（あらかじめ指定された1記事）を上書き更新する。
        公開ステータスや公開日時は変更しない。
        引数:
          new_title: リライト後のタイトル
          new_content_html: リライト後の本文HTML全文
        戻り値: 更新結果を説明する文字列
        """
        try:
            result = update_post(client, post_id, title=new_title, content=new_content_html)
            return f"更新成功: id={result['id']}, url={result['link']}"
        except (WordPressError, ConfigError) as e:
            return f"更新失敗: {e}"

    return [update_wordpress_post_tool]


def build_research_tools(client: ClientConfig) -> list:
    """リサーチャーが話題の重複を避けるために、既存記事のタイトル一覧を取得できるツール。"""

    @tool("get_recent_titles")
    def get_recent_titles_tool(count: int = 15) -> str:
        """
        サイトに既に投稿されている直近の記事タイトル一覧を取得する。
        新しい記事のテーマが既存記事と重複しないようにするために、企画の前に必ず確認すること。
        """
        try:
            titles = get_recent_titles(client, count=count)
            if not titles:
                return "（まだ投稿がありません）"
            return "\n".join(f"- {t}" for t in titles)
        except Exception as e:
            return f"取得エラー: {e}"

    return [get_recent_titles_tool]


if __name__ == "__main__":
    import sys

    from src.config_loader import get_client

    if len(sys.argv) < 2:
        print("使い方: python -m tools.wordpress_tool <client_id>")
        sys.exit(1)

    c = get_client(sys.argv[1])
    try:
        test_connection(c)
        print(f"[OK] {c.id} ({c.display_name}) への接続に成功しました。")
    except (WordPressError, ConfigError) as e:
        print(f"[NG] {e}")
        sys.exit(1)

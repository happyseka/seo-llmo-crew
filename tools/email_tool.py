"""
email_tool.py
==============
Gmailのアプリパスワードを使い、SMTP経由でメール通知を送るモジュール。

このシステムからのメールは主に2種類:
  1. 投稿報告  : 記事を1本公開するたびに送る短い通知
  2. 作業報告  : 週次・月次でまとめて送る「何をしたか／根拠／今後の予定」の報告
"""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from crewai.tools import tool

from src.config_loader import ConfigError, require_env


class EmailError(RuntimeError):
    pass


def send_email(to: str, subject: str, body_text: str) -> None:
    """
    シンプルなテキストメールを送信する。
    必要な環境変数: NOTIFY_SMTP_HOST, NOTIFY_SMTP_PORT, NOTIFY_SMTP_USER,
                    NOTIFY_SMTP_APP_PASSWORD, NOTIFY_FROM_NAME(任意)
    """
    if not to:
        raise EmailError("送信先メールアドレスが指定されていません。")

    host = require_env("NOTIFY_SMTP_HOST")
    port = int(require_env("NOTIFY_SMTP_PORT"))
    user = require_env("NOTIFY_SMTP_USER")
    app_password = require_env("NOTIFY_SMTP_APP_PASSWORD")
    from_name = "SEO記事自動投稿システム"
    try:
        from_name = require_env("NOTIFY_FROM_NAME")
    except ConfigError:
        pass

    msg = MIMEMultipart()
    msg["From"] = formataddr((from_name, user))
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(user, app_password)
            server.sendmail(user, [to], msg.as_string())
    except smtplib.SMTPException as e:
        raise EmailError(f"メール送信に失敗しました: {e}") from e


def notify_batch_scheduled(
    client_display_name: str,
    notify_email: str,
    period_label: str,
    articles: list[dict],
) -> None:
    """
    月末バッチで作成した記事をまとめて報告する「下書き＆予約投稿報告」メール。
    articles の各要素は {"scheduled_at_label", "title", "preview_url", "status"} を想定。
    """
    subject = f"【{client_display_name}】{period_label}分の記事を{len(articles)}本、予約投稿しました"
    lines = [
        f"{client_display_name} 様\n",
        f"{period_label}分の記事を{len(articles)}本作成し、WordPressに予約投稿として登録しました。",
        "公開前に、下記の確認用リンクから内容をご確認ください。\n",
    ]
    for i, a in enumerate(articles, 1):
        lines.append(
            f"{i}. [{a.get('scheduled_at_label', '')}] {a.get('title', '')}\n"
            f"   確認用リンク: {a.get('preview_url', '(未発行)')}\n"
            f"   ステータス: {a.get('status', '')}"
        )
    lines.append(
        "\n内容に修正が必要な場合は、WordPress管理画面から該当記事を直接編集していただくか、"
        "担当までご連絡ください。修正がなければ、上記日時に自動で公開されます。"
    )
    lines.append("\n------------------------------------------------\n本メールはCrewAI記事自動生成システムによる自動送信です。")
    send_email(notify_email, subject, "\n".join(lines))


def notify_rewrite_report(
    client_display_name: str,
    notify_email: str,
    period_label: str,
    rewrites: list[dict],
) -> None:
    """
    「リライト報告」メール。どの記事のどの部分を、なぜリライトしたのかをまとめて送る。
    rewrites の各要素は {"page_path", "old_title", "new_title", "reason", "change_summary", "updated"} を想定。
    """
    if not rewrites:
        subject = f"【{client_display_name}】{period_label}のリライト報告（対象記事なし）"
        body = (
            f"{client_display_name} 様\n\n"
            f"{period_label}のアナリティクス分析の結果、優先的にリライトすべき記事は見つかりませんでした。\n"
            f"（表示回数・クリック率ともに大きな問題は見られませんでした）\n\n"
            f"------------------------------------------------\n本メールはCrewAI記事自動生成システムによる自動送信です。"
        )
        send_email(notify_email, subject, body)
        return

    subject = f"【{client_display_name}】{period_label}のリライト報告（{len(rewrites)}件）"
    lines = [f"{client_display_name} 様\n", f"{period_label}のアクセス解析に基づき、以下の記事をリライトしました。\n"]
    for i, r in enumerate(rewrites, 1):
        status = "更新完了" if r.get("updated") else "更新失敗（要確認）"
        lines.append(
            f"{i}. {r.get('old_title', '')}\n"
            f"   → 新タイトル: {r.get('new_title', '')}\n"
            f"   対象ページ: {r.get('page_path', '')}\n"
            f"   リライトした理由（根拠）: {r.get('reason', '')}\n"
            f"   変更内容: {r.get('change_summary', '')}\n"
            f"   ステータス: {status}\n"
        )
    lines.append("------------------------------------------------\n本メールはCrewAI記事自動生成システムによる自動送信です。")
    send_email(notify_email, subject, "\n".join(lines))


def notify_work_report(
    client_display_name: str,
    notify_email: str,
    period_label: str,
    report_text: str,
) -> None:
    """週次・月次の「作業報告」メール（何をしたか・根拠・今後の予定）を送る。"""
    subject = f"【{client_display_name}】作業報告（{period_label}）"
    body = (
        f"{client_display_name} 様\n\n"
        f"{period_label}のSEO記事自動化システムの作業報告です。\n\n"
        f"{report_text}\n\n"
        f"------------------------------------------------\n"
        f"本メールはCrewAI記事自動生成システムによる自動送信です。\n"
    )
    send_email(notify_email, subject, body)


# ---------------------------------------------------------------------
# CrewAI Agent 用ツール
# ---------------------------------------------------------------------

def build_email_tools(client_display_name: str, notify_email: str) -> list:
    """アナリスト等のエージェントが、作成した報告文をそのままメール送信できるようにするツール。"""

    @tool("send_report_email")
    def send_report_email_tool(subject: str, body_text: str) -> str:
        """
        作成した作業報告・分析レポートの文章を、担当者宛にメールで送信する。
        引数:
          subject: メール件名
          body_text: メール本文（日本語プレーンテキスト。「実施内容」「根拠」「今後の予定」を含めること）
        戻り値: 送信結果を表す文字列
        """
        try:
            send_email(notify_email, f"【{client_display_name}】{subject}", body_text)
            return f"送信成功: {notify_email} 宛に '{subject}' を送信しました。"
        except EmailError as e:
            return f"送信失敗: {e}"

    return [send_report_email_tool]


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("使い方: python -m tools.email_tool <送信先メールアドレス>")
        sys.exit(1)

    try:
        send_email(sys.argv[1], "【テスト】SEO記事自動投稿システム 疎通確認", "このメールが届いていればSMTP設定は正常です。")
        print("[OK] テストメールを送信しました。")
    except EmailError as e:
        print(f"[NG] {e}")
        sys.exit(1)

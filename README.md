# SEO/LLMO記事自動化システム（CrewAI）

CrewAIを使い、リサーチャー・ライター・編集者・アナリストの4つのAIエージェントが連携して、
WordPressサイトへの記事の企画・執筆・予約投稿・改善（リライト）・報告までを自動化するシステムです。

セットアップ手順は、別途お渡ししている **「セットアップガイド.docx」** を参照してください。
このREADMEは技術的な補足情報です。

## 全体の流れ（月次サイクル）

毎月、GitHub Actionsが自動的に以下を実行します（`.github/workflows/monthly-cycle.yml`）。

1. **記事作成バッチ**（翌月分をまとめて作成）
   リサーチ → 企画 → 執筆 → 推敲 → 挿絵・アイキャッチ作成 → 外部確認用プレビュー生成 → WordPressへ予約投稿
2. **下書き＆予約投稿報告**（メール）
   その月に予約投稿した記事の一覧（日付・タイトル・確認用リンク）を報告
3. **記事改善バッチ**（先月分のアクセス解析→リライト）
   Google Analytics 4 / Search Console のデータを分析し、リライトすべき記事を特定して書き直し、WordPressを更新
4. **リライト報告**（メール）
   どの記事の何を、なぜ直したのかを報告
5. **作業報告**（メール）
   1〜4全体の実施内容・根拠・今後の方針をまとめて報告

## ディレクトリ構成

```
config/
  clients.example.yaml   クライアント設定のサンプル（実運用ではclients.yamlをこのファイルからコピーして作成）
  clients.yaml            実際のクライアント設定（Gitで管理。パスワード等は含まない）
  secrets/                 Googleサービスアカウント鍵の置き場所（Gitでは管理しない）
src/
  config_loader.py         設定・認証情報の読み込み
  date_utils.py             予約投稿日時・対象月の計算
  schemas.py                 エージェントの構造化出力スキーマ（Pydantic）
  agents/definitions.py     4エージェント（リサーチャー/ライター/編集者/アナリスト）の定義
  tasks/                       各エージェントに与えるタスク定義
  crew_article.py            記事作成バッチの実行本体
  crew_improve.py            記事改善バッチの実行本体
  crew_report.py             統合作業報告の実行本体
tools/
  wordpress_tool.py         WordPress REST API連携（投稿・予約投稿・更新・画像アップロード）
  image_tool.py               AI不使用のアイキャッチ・挿絵自動生成（Pillow）
  preview_tool.py             外部確認用プレビューページ生成（GitHub Pages公開用）
  email_tool.py                通知メール送信（Gmail SMTP）
  analytics_tool.py           GA4 / Search Console 連携
fonts/
  NotoSansJP-Variable.ttf   画像生成用の日本語フォント（OFLライセンス）
docs/
  previews/                    生成されたプレビューページ（GitHub Pagesで公開）
scripts/check_setup.py       セットアップ確認スクリプト
main.py                        CLIエントリポイント
.github/workflows/            GitHub Actionsのスケジュール実行定義
```

## ローカルでのコマンド例

```bash
pip install -r requirements.txt
cp config/clients.example.yaml config/clients.yaml   # 編集して使う
cp .env.example .env                                    # 編集して使う

# 設定確認
python scripts/check_setup.py

# 翌月分の記事をまとめて作成・予約投稿
python main.py create-batch --client all

# 先月分のアナリティクスを解析してリライト
python main.py improve --client all

# 上記を通しで実行し、最後に統合の作業報告を送る
python main.py monthly-cycle --client all

# 年月を指定して実行することも可能
python main.py monthly-cycle --client client_a --article-year 2026 --article-month 9 --improve-year 2026 --improve-month 8
```

## クライアントを追加する方法

1. `config/clients.yaml` に新しいクライアントのブロックをコピー＆ペーストして追加する
   （`env_prefix` は他のクライアントと重複しない値にする）
2. `.env`（またはGitHub Secrets）に、そのクライアント用の認証情報を追加する
3. `.github/workflows/monthly-cycle.yml` と `check-setup.yml` 内のコメントアウトされている
   `CLIENT_B` のブロックをコピーして有効化する（コード側の変更は不要）

## ライセンス・注意事項

- `fonts/NotoSansJP-Variable.ttf` は Google Noto Fonts（SIL Open Font License 1.1）です。
- 本システムはAI（Claude API）が生成した文章を、人によるレビューなしで自動公開しない設計です
  （必ず「予約投稿」として登録し、プレビューリンクで事前確認できるようにしています）。
  最終的な公開内容の責任は運用者にあります。定期的に生成内容をご確認ください。

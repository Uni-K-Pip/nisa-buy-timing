# NISA 買い時

NISA 成長投資枠で投資信託を買うときの参考指標を表示する PWA です。直近の価格を同じ投信の過去最大5年と比較したスコア、基準価額の推定値、購入方法の過去検証を確認できます。スマートフォンではブラウザーからホーム画面に追加できます。

投資助言ではありません。スコアや確率は過去データに基づき、推定値と予測は外れることがあります。注文締切、約定日、受渡日、年内受渡の最終注文日は推定です。SBI証券などの公式画面で確認し、ご自身で判断・注文してください。SBI証券や運用会社とは無関係です。

## データ元

- 基準価額と分配金は投資信託協会の[投信総合検索ライブラリー](https://toushin-lib.fwg.ne.jp/)。
- 指数、ETF、米ドル／円、VIX は [Yahoo Finance](https://finance.yahoo.com/) の終値を yfinance で取得。
- 日本と NYSE の休業日は [holidays](https://github.com/vacanza/holidays) を利用。

## 最初の公開と通知の設定

1. リポジトリの **Settings → Pages → Build and deployment** で **GitHub Actions** を選びます。**Actions → Pages → Run workflow** で `main` の初回ビルドを実行します。
2. 通知を使う場合は、権限のある GitHub CLI でログインし、手元で `python scripts/setup_push.py` を実行します。対象リポジトリが異なる場合は `--repo OWNER/REPO` を指定してください。鍵の登録後に Pages ワークフローを再実行します。鍵を再発行すると既存の購読が無効になります。
3. 公開したアプリを開き、設定で「通知を有効にする」を実行します。iOS ではホーム画面に追加し、追加したアイコンから開きます。
4. 設定で「通知の設定をコピー」を押し、リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で `PUSH_CONFIG` として貼り付けます。計画や条件を変更したら貼り直します。複数端末に送る場合は Secret の `subscriptions` に各端末の購読をまとめます。

Pages の定期更新は平日 7:30 と 21:30（日本時間）に予定され、通知の判定は朝の更新後に行います。公開リポジトリでリポジトリの活動が60日間ないと、GitHub Actions のスケジュールが無効になります。再開するには **Actions → Pages → Enable workflow** を押します。すぐ更新する場合はあわせて **Run workflow** を実行します。

## 手元で動かす

リポジトリのルートで Python 3.13 と Node.js を使います。Windows の例です。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m nbt.build --out site/data
.venv\Scripts\python -m http.server -d site 8000
```

ブラウザーで `http://localhost:8000/` を開きます。ビルド時はデータ元への通信が必要です。

```powershell
.venv\Scripts\python -m pytest -q
node --test "tests/js/*.test.mjs"
.venv\Scripts\python scripts/privacy_check.py
```

## 個人データ

計画、金額、購入の記録、ウォッチ、通知ルールはブラウザーのローカルストレージに保存します。設定から JSON への書き出し・読み込み・全削除ができます。書き出したファイルは端末内で保管してください。通知を利用する場合、手動で GitHub Actions の Secret に登録した購読情報と通知条件を Actions が読み取ります。通知設定の JSON からは購入金額と計画名を除いています。通知をやめる場合は、アプリの設定で購読を解除し、その端末の購読を Secret から削除してください。

公開リポジトリ、Pages の生成データ、Actions のログに計画、購読情報や秘密鍵を載せないでください。ローカルで通知の試験出力を保存する場合は `python -m nbt.notify --dry-run push-config-dry-run.json` を使えます。試験出力にも予定日などの通知内容が含まれます。

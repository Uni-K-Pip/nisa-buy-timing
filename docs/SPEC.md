# nisa-buy-timing 仕様(v0.1)

NISA の成長投資枠で投資信託を買うときの「買い時」を、過去データに基づく参考指標で示す PWA。
スマホのホーム画面に追加して使う。GitHub Pages(public)で配信し、データの更新と通知は GitHub Actions が受け持つ。

## 0. 前提と非目的

- 将来の値動きは当てられない。アプリが示すのは「その投信が、過去の自分自身と比べてどれだけ安い局面か」と、その指標が過去に役立ったかの検証結果。断定的な表現(「今が底」「必ず上がる」)を画面と通知に出さない。
- 投資助言ではない。注文は行わない。SBI 証券や運用会社とは無関係の個人ツールであり、ロゴや名称を公式のように使わない。
- 注文締切、約定日、受渡日、年内受渡の最終日はアプリでは「推定」。公式の画面で確かめるよう常に添える。

## 1. 個人データの決まり(最優先)

リポジトリは public。次を必ず守る。

1. 購入計画、金額、購入記録、ウォッチ中の銘柄、通知ルールは、端末の `localStorage` だけに置く。リポジトリ、ビルド成果物(`site/data`)、Actions のログに出さない。
2. 通知に必要な情報(Push の購読情報とルール)は、ユーザーがアプリでコピーして GitHub Actions の Secret `PUSH_CONFIG` に貼る。コード側は Secret を読むだけで、内容を一切ログに出さない(件数だけ)。
3. VAPID の秘密鍵は Secret `VAPID_PRIVATE_KEY`。公開鍵は Actions の Variable `VAPID_PUBLIC_KEY` から `site/data/push.json` に書く(公開鍵は公開してよい)。鍵の生成と登録はユーザーが手元で `scripts/setup_push.py` を実行して行う。
4. コード、文書、テスト、既定値に、個人名、メールアドレス(GitHub の noreply と example ドメインを除く)、手元の絶対パス、実際の金額計画を書かない。計画の画面の既定値は空にする。
5. サイトは外部へ通信しない(CDN、Web フォント、解析タグを使わない)。CSP で `'self'` に限る。`robots.txt` で全拒否、`<meta name="robots" content="noindex,nofollow">` を付ける。
6. `scripts/privacy_check.py` が、追跡対象と未追跡(ignore されていない)ファイルを走査し、上の違反を見つけたら終了コード 1 にする。CI で毎回走らせる。

## 2. 構成

```
config/funds.json          対象投信の定義(公開してよい一般情報だけ)
nbt/                       Python パッケージ(データ取得、計算、ビルド、通知)
  calendar.py  fetch.py  series.py  indicators.py  score.py  ml.py
  backtest.py  settlement.py  build.py  notify.py
scripts/privacy_check.py   個人情報の走査
scripts/setup_push.py      VAPID 鍵の生成と gh への登録(ユーザーが手元で実行)
scripts/make_icons.py      PWA アイコン(PNG)の生成。標準ライブラリだけ
site/                      PWA 本体(ビルド不要の静的ファイル、ES modules)
  index.html  styles.css  sw.js  manifest.webmanifest  robots.txt  app-config.json
  js/  icons/  tests/      (site/data/ はビルドで生成し、Git に入れない)
tests/                     pytest(ネットワークを使わない)
.github/workflows/ci.yml   テストと privacy_check
.github/workflows/pages.yml データ更新、Pages への配備、通知
requirements.txt           Python の依存(版を固定)
```

Python 3.13。依存は pandas、numpy、yfinance、scikit-learn、holidays、pywebpush、requests、pytest。版は `requirements.txt` で `==` 固定する(手元の `.venv` に入っている版に合わせる)。

## 3. データ元(2026-11-22 に取得を確認済み)

| データ | 取得方法 | 備考 |
|---|---|---|
| 投信の基準価額 | 投資信託協会「投信総合検索ライブラリー」の CSV: `https://toushin-lib.fwg.ne.jp/FdsWeb/FDST030000/csv-file-download?isinCd=<ISIN>&associFundCd=<協会コード>` | 文字コードは cp932(応答ヘッダの utf-8 は誤り)。列は `年月日,基準価額(円),純資産総額（百万円）,分配金,決算期`。日付は `2026年11月20日` 形式。設定来の全期間 |
| 指数・ETF・VIX | yfinance(`yf.download(..., auto_adjust=False)` の `Close`) | `^NYFANG` は 2014-09-22 から。`^GSPC`、`ACWI`、`^VIX` |
| 為替 | yfinance `USDJPY=X` | |
| 祝日 | `holidays.country_holidays("JP")`、`holidays.financial_holidays("NYSE")` | |

取得は 3 回まで再試行(指数的に待つ)、タイムアウト 30 秒。HTTP の User-Agent は `nisa-buy-timing/0.1 (+https://github.com/Uni-K-Pip/nisa-buy-timing)`。基準価額の取得に失敗した銘柄は、代理系列(指数×為替)だけで計算を続け、`status.warnings` に記録する。指数の取得に失敗したら、その銘柄は基準価額だけで計算する。両方失敗したらビルドを失敗させる(前回の Pages が残る)。

### 3.1 config/funds.json

```json
{
  "default_watch": ["ifree-next-fang-plus"],
  "funds": [
    {
      "id": "ifree-next-fang-plus",
      "name": "iFreeNEXT FANG+インデックス",
      "short_name": "FANG+",
      "isin": "JP90C000FZD4",
      "association_code": "04311181",
      "nav_source": {"type": "toushin_lib"},
      "proxy": {"index_ticker": "^NYFANG", "index_label": "NYSE FANG+指数", "fx_ticker": "USDJPY=X"},
      "fx_component": true,
      "order_closed_calendars": ["NYSE"],
      "settlement": {"trade_lag_bd": 1, "settle_bd_from_order": 6, "order_cutoff_jst": "15:00", "verified": false},
      "nisa": {"growth": true, "tsumitate": null}
    }
  ]
}
```

ほかに次の 2 本を入れる(`default_watch` には入れない)。

- `emaxis-slim-sp500`: eMAXIS Slim 米国株式(S&P500)、ISIN `JP90C000GKC6`、協会コード `03311187`、代理 `^GSPC`×`USDJPY=X`、休業 NYSE。
- `emaxis-slim-all-country`: eMAXIS Slim 全世界株式(オール・カントリー)、ISIN `JP90C000H1T1`、協会コード `0331418A`、代理 `ACWI`×`USDJPY=X`、休業 NYSE。

受渡の値(`settle_bd_from_order` など)は未確認の推定なので、3 本とも `verified: false`。銘柄の追加はこのファイルに足すだけで済むようにする(ISIN と協会コードがあれば基準価額、ティッカーがあれば代理系列)。

## 4. 計算

### 4.1 営業日と受渡(`calendar.py`、`settlement.py`)

- 国内営業日: 平日で、日本の祝日でなく、12/31 と 1/1〜1/3 でない日。
- 注文できる日: 国内営業日で、銘柄の `order_closed_calendars`(NYSE の休場日)に当たらない日。
- 約定日: 注文日の `trade_lag_bd` 国内営業日後。
- 受渡日: 注文日を 1 日目として数えた `settle_bd_from_order` 番目の国内営業日。
- 年内受渡の最終注文日: その年の注文できる日のうち、受渡日がその年の最後の国内営業日以前になる最も遅い日。
- 確認用の値(テストに入れる): 2026 年、NYSE 休場(12/25)を考慮して、N=6 なら 2026-12-23、N=5 なら 2026-12-24、N=4 なら 2026-12-24(12/25 は注文不可)、NYSE を考慮しない N=4 なら 2026-12-25。2026 年の最後の国内営業日は 12/30。
- 同じ計算を PWA 側(`site/js/calendar.js`)にも持つ。両方に上の確認用の値のテストを書く。PWA は `site/data/calendar.json` の休日一覧を使う。

### 4.2 価格系列(`series.py`)

- 基準価額系列: CSV の基準価額。分配金がある日は再投資した値に調整する(調整係数 = 累積の (1 + 分配金 / 基準価額))。日付は日本の営業日。
- 代理系列: 指数終値 × USDJPY(同じ米国日付の値。為替が欠けたら直前の値)。米国日付 t の代理値は、t より後の最初の国内営業日の基準価額の推定材料とみなす。
- 推定基準価額(nowcast): 最新の基準価額の日付 D について、D の基準価額に対応する米国日付(D より前の最後の米国営業日)より新しい代理値があれば、`最新基準価額 × 最新代理値 / 対応する代理値` を推定値にする。推定誤差の目安として、過去 1 年の「基準価額の日次騰落率 − 代理系列の対応する日次騰落率」の標準偏差(%)を添える。
- 計算に使う主系列は、基準価額があればそれ、なければ代理系列(円換算)。

### 4.3 指標(`indicators.py`)

主系列 P(国内営業日ごと)から計算する。

| キー | 定義 | 画面の名前 |
|---|---|---|
| `dd252` | P / 直近 252 日の最高値 − 1 | 52 週高値からの下落率 |
| `ma200_dev` | P / 200 日移動平均 − 1 | 200 日移動平均からの乖離 |
| `ma25_dev` | P / 25 日移動平均 − 1 | 25 日移動平均からの乖離 |
| `rsi14` | Wilder の RSI(14) | RSI(14) |
| `fx_dev` | USDJPY / 200 日移動平均 − 1(`fx_component: true` の銘柄だけ) | 円安・円高の度合い |
| `ret5`、`ret20`、`ret60` | 騰落率 | |
| `vol20` | 日次対数収益率の 20 日標準偏差(年率) | |
| `vol_ratio` | vol20 / 252 日の同じ値 | |
| `vix`、`vix_chg20` | `^VIX` の終値と 20 日変化(取れたときだけ。日付は米国日付→翌国内営業日に対応) | |

### 4.4 買い時スコア(`score.py`)

- 各要素について、その時点までの直近 1260 日(約 5 年。足りなければ 120 日以上ある範囲)の中での百分位 `pct`(現在値以下の割合)を出す。未来のデータを使わない(t の値は t までのデータだけで決まる)。
- 安さ `cheapness = 100 × (1 − pct)`(値が低いほど安いとみなす要素: dd252、ma200_dev、ma25_dev、rsi14、fx_dev)。
- スコア = 重み付き平均。重みは dd252 0.30、ma200_dev 0.25、ma25_dev 0.15、rsi14 0.20、fx_dev 0.10。使えない要素は除いて重みを正規化する。
- 区分: 80 以上「かなり割安圏」、60〜79「割安寄り」、40〜59「中立」、20〜39「割高寄り」、20 未満「かなり割高圏」。いつも「過去 5 年の同じ投信との比較」と添える。
- 各要素に日本語の説明文を付ける。例: 「52週高値から −8.7%(過去5年で安い方から 12%)」。

### 4.5 機械学習(実験、`ml.py`)

- 目的変数: 約定日(t の翌営業日)の価格より、その 20 営業日後の価格のほうが安いか(`P[t+1+20] < P[t+1]`)。画面の言い方は「20営業日待てば安く買えた確率」。
- 特徴量: 4.3 の dd252、ma200_dev、ma25_dev、rsi14、ret5、ret20、ret60、vol20、vol_ratio、fx_dev(対象なら)、vix と vix_chg20(取れたら)。
- モデル: `StandardScaler` + `LogisticRegression(C=0.5, max_iter=1000)`。
- ウォークフォワード検証: 750 件の学習データがたまってから、21 営業日ごとに学習し直し、次の 21 日を予測する。学習に使う行は、その時点で答えが確定している行だけ(行 i は i+1+20 が学習時点以前のときだけ)。
- 指標: AUC、Brier、基準 Brier(その時点までの正例率で予測した場合)、Brier スキル = 1 − Brier / 基準 Brier、件数、10 分位の較正表。
- 有効の判定: 件数 250 以上、Brier スキル 0.01 超、AUC 0.55 超。満たさなければ `valid: false` とし、画面に「過去の検証では偶然と区別できません。参考にしないでください」と大きく出す。
- 最新の確率は、答えが確定している全行で学習したモデルで出す。

### 4.6 検証(`backtest.py`)

「決めた日に分けて買う」と比べて、スコアを見て買うと平均取得単価がどう変わったかを過去データで調べる。

- 判断は国内営業日 t に行い、約定は P[t+1]。
- 期間 W 営業日、回数 K、各回同額。k 回目の小区間は `[floor(k·W/K), floor((k+1)·W/K) − 1]`。
- 定期購入(基準): 各小区間の初日に買う。
- 一括: 期間の初日に全額。
- スコア戦略(閾値 T): 各小区間で、スコアが T 以上の最初の日に買う。なければ小区間の最終日に買う。すでに今の回を買ったあと、スコアが T+15(上限 95)以上なら次の回を前倒しで買ってよい(1 日 1 回まで)。
- ML 戦略(q = 0.4): 各小区間で「待てば安く買えた確率」が q 以下の最初の日に買う。なければ最終日。ウォークフォワードの予測がある期間だけ。
- 平均取得単価は同額購入なので調和平均。比較値 = 戦略の平均単価 / 定期購入の平均単価 − 1(%、負なら安く買えた)。
- 開始日は 5 営業日ごと。グリッド: W ∈ {20, 40, 60, 120}、K ∈ {1, 2, 3, 4, 6}(K ≤ W)、T ∈ {60, 70, 80}。
- 出す値: 件数、平均、中央値、勝率(安く買えた割合)、5% 点と 95% 点。直近 3 年だけの同じ値も。一括と定期購入の比較も同じ形で。

## 5. ビルドの出力(`python -m nbt.build --out site/data`)

すべて UTF-8 の JSON。数値は丸める(価格は小数 2 桁、% は小数 2 桁)。個人データは入れない。

- `latest.json`: `schema`、`generated_at`(JST の ISO 8601)、`run_kind`、`disclaimer`、`sources`(名前と URL)、`funds[]`。各 fund に `id`、`name`、`short_name`、`series_kind`(`nav`/`proxy`)、`nav`(日付、値、前日比)、`nowcast`(基にした米国日付、推定値、変化率、誤差の目安)、`proxy`(指数のティッカー・名前・日付・値・前日比、為替の値)、`score`(値、区分、区分名、要素の一覧と説明、基準日)、`ml`(確率、基準日、`valid`、指標、注記)、`settlement`(`verified`、各パラメータ、今年の年内受渡の最終注文日と受渡日と残り営業日、今後 5 回の注文できる日)、`status`(取得の成否と警告)。
- `series/<id>.json`: `dates`、`value`(主系列)、`nav`、`proxy_jp`(円換算の代理値)、`index`、`score`、`ml_prob`。欠けは null。全期間の日次。
- `backtest/<id>.json`: 4.6 のグリッドの結果と、条件の説明文。
- `ml/<id>.json`: 4.5 の指標と較正表。
- `calendar.json`: 今年と来年の、日本の休業日(祝日と年末年始)と NYSE の休場日。
- `push.json`: `{"vapid_public_key": "<環境変数 VAPID_PUBLIC_KEY の値>" | null}`。
- `meta.json`: ビルドの時刻、各データの最新日付、取得の成否。

取得部分は差し替えられるようにし、テストではネットワークを使わずに偽のデータでビルドを通す。

## 6. PWA(`site/`)

- ビルド不要の静的ファイル。ES modules。外部ライブラリを使わない(チャートは自前の SVG)。相対パスだけを使う(Pages では `/nisa-buy-timing/` の下に置かれる)。
- スマホ向けの縦画面を主に、PC 幅でも崩れない。ダークモード対応。日本語。下部タブで画面を切り替える。
- `sw.js`: アプリの殻をキャッシュ(オフラインで開ける)。`data/` はネットワーク優先、失敗したらキャッシュ。`push` を受けて通知を出し、通知を押したらアプリを開く。版を上げたら古いキャッシュを消す。
- `manifest.webmanifest`、アイコン(192、512、apple-touch-icon 180 の PNG)。iOS でホーム画面に追加できるメタタグ。
- CSP は meta タグで `default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; manifest-src 'self'; worker-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'`。インラインのスクリプトとスタイルを使わない。
- 初回起動時に注意書き(投資助言ではない、予測は外れうる、締切や受渡日は公式で確認、SBI 証券とは無関係)を出し、同意を `localStorage` に残す。どの画面の下部にも短い注意書き。

### 6.1 画面

1. **今日**: ウォッチ中の銘柄ごとのカード。スコア(大きな数字と区分、メーター)、上位の理由 3 つ、基準価額と推定基準価額、指数と為替の前日比、ML の確率と有効・無効の表示、データの日付(古ければ警告)、年内受渡の最終注文日(推定)までの残り営業日。計画があれば、次の回、警告、前倒しの条件に届いたか。
2. **チャート**: 銘柄を選び、期間(1 年、3 年、全期間)を切り替える。価格の線とスコアの帯。端末に記録した購入日の印。
3. **計画**: 購入計画の作成と編集(6.2)。
4. **検証**: 計画の条件(期間 = 計画の最初の予定日から最後の予定日までの営業日数に近い W、回数 K、閾値 T)に最も近いグリッドの結果を、平易な文で示す(例: 「過去 380 回の期間で、スコアを見て買う方法は定期購入より平均 0.4% 安く、安く買えたのは 56%」)。差が小さいことも隠さない。ML の指標と較正表。計画がなければ既定値(W=40、K=3、T=70)。
5. **設定**: ウォッチする銘柄の選択、通知の設定(6.3)、データの書き出し・読み込み・全削除、注意書きの再表示、データ元の一覧。

### 6.2 購入計画(`site/js/plan.js` は DOM に触れない純粋な関数で書き、node:test で試す)

計画のデータ:

```
{ id, fund_id, title, year, budget, threshold_score (既定 70), pull_forward_score (既定 85),
  levels: [{kind: "index"|"nav", op: "<=", value}],
  drop_rule: {kind: "index"|"nav", reference_value, pct} | null,
  installments: [{id, planned_date, amount, status: "planned"|"ordered"|"executed"|"cancelled",
                  order_date, trade_date, settle_date, note}],
  official_last_order_date: null | "YYYY-MM-DD",
  nisa_used_this_year: null | number }
```

- 予算と回数から各回の金額を割り振るボタン(端数は最後の回に寄せる)。
- 確認(エラーと警告、画面に出す):
  - 取消以外の金額の合計が予算を超える → エラー。
  - `nisa_used_this_year` + この年に受渡予定の未受渡分 > 2,400,000 → エラー「成長投資枠の年間上限を超えます」。
  - 予定日を過ぎて status が planned → 警告「予定日を過ぎています。注文済みか確かめてください(二重注文に注意)」。
  - 予定日が注文できない日 → 警告と、次に注文できる日。
  - 予定日が年内受渡の最終注文日(公式の日が入っていればそれ、なければ推定)より後 → 警告「受渡が翌年になり、翌年の枠を使う可能性があります」。
  - 同じ日に注文済みの回が 2 つ以上 → 警告。
  - 現在のスコアが前倒しの閾値以上で、未注文の回がある → 情報「前倒しの条件に達しています(判断はご自身で)」。
  - 価格の条件(levels、drop_rule)に届いた → 情報。
- 回ごとに「注文した」「約定した」を記録でき、約定日・受渡日は SBI の画面の値を手で入れる。
- すべて `localStorage`(キー `nbt:v1`)。読み書きは try/catch で包み、使えなくても画面は動く。書き出しは JSON ファイルのダウンロード、読み込みは同じ形のファイル。

### 6.3 通知(Web Push)

- 設定画面で「通知を有効にする」→ `push.json` の公開鍵で購読する。公開鍵がない場合は、`scripts/setup_push.py` の実行が必要と案内する。iOS はホーム画面に追加した PWA だけで動くことを案内する。
- 「通知の設定をコピー」で次の JSON を作る。金額と計画名は入れない(ラベルは「1回目」などの自動の名前だけ)。

```
{ "v": 1,
  "subscriptions": [<PushSubscription.toJSON()>],
  "rules": {
    "funds": ["<id>", ...],
    "score_at_least": 70 | null,
    "levels": [{"fund_id", "kind": "index"|"nav", "op": "<=", "value"}],
    "drops": [{"fund_id", "kind", "reference_value", "pct"}],
    "dates": [{"fund_id", "date": "YYYY-MM-DD", "label": "2回目", "days_before": [1, 0]}],
    "year_end": {"fund_ids": [...], "days_before": [5, 1]},
    "ml": {"enabled": false, "prob_at_most": 0.4, "valid_only": true}
  } }
```

- 画面に、GitHub の `Settings → Secrets and variables → Actions → New repository secret` に名前 `PUSH_CONFIG` で貼る手順と、そのページへのリンク(`site/app-config.json` の `repo` から作る)を出す。計画を変えたら貼り直しが要るので、最後にコピーした内容のハッシュを覚え、違ったら「通知の設定が古くなっています」と出す。
- `nbt/notify.py`(朝の実行だけ): `PUSH_CONFIG` と `VAPID_PRIVATE_KEY` が環境変数にあるときだけ動く。判定は状態を持たない。
  - スコア、価格の条件、下落率: 最新日に条件を満たし、その前の営業日に満たしていなかったら通知(またぎ)。
  - 日付: JST の今日 = 予定日 − days_before。本文に「注文済みなら不要です」。
  - 年内受渡: 最終注文日(推定)までの残り国内営業日が days_before に入る日。
  - ML: 有効なときだけ、確率が閾値以下にまたいだら。
- 本文の例: 題「買い時シグナル: FANG+」、本文「スコア 82(かなり割安圏)。52週高値から −12.3%。判断と注文はご自身で。」。通知を押すとアプリを開く。
- 送信は pywebpush。VAPID の `sub` は環境変数 `VAPID_SUBJECT`、なければ `site/app-config.json` の `site_url`(メールアドレスを使わない)。TTL 12 時間。
- ログに出すのは `notify: rules=<n> triggered=<n> sent=<n> failed=<n> expired=<n>` だけ。例外は型の名前だけ。購読先の URL、鍵、ラベル、値は出さない。410/404 は期限切れとして数える。
- 手元の試験用に `--dry-run <出力ファイル>` で、送る内容をファイルへ書く。環境変数 `GITHUB_ACTIONS=true` のときは `--dry-run` を拒否する。

### 6.4 scripts/setup_push.py(ユーザーが手元で実行)

- py_vapid で鍵を作り、`gh secret set VAPID_PRIVATE_KEY`(標準入力で渡し、画面に出さない)と `gh variable set VAPID_PUBLIC_KEY` を実行する。`--repo` の既定は `Uni-K-Pip/nisa-buy-timing`。鍵をファイルに残さない。
- すでに鍵があるときは `--force` なしでは上書きしない(購読がすべて無効になるため)。

## 7. ワークフロー

- `ci.yml`: すべての push と PR。Python 3.13 で `pip install -r requirements.txt`、`pytest -q`、Node で `node --test site/tests/`、`python scripts/privacy_check.py`。
- `pages.yml`: `main` への push、`workflow_dispatch`、schedule の 2 本(`30 22 * * 0-4` = 平日 7:30 JST の朝、`30 12 * * 1-5` = 平日 21:30 JST の夜)。権限は `contents: read`、`pages: write`、`id-token: write`。同時実行は 1 つ。手順: checkout → setup-python(pip のキャッシュ)→ install → build → upload-pages-artifact(`site`)→ deploy-pages → 朝の実行だけ notify(`continue-on-error: true`。Secret がなければ何もしない)。build には `VAPID_PUBLIC_KEY` を `vars` から渡す。
- 使う Actions: `actions/checkout@v5`、`actions/setup-python@v6`、`actions/setup-node@v5`、`actions/configure-pages@v5`、`actions/upload-pages-artifact@v4`、`actions/deploy-pages@v4`。

## 8. テスト(ネットワークを使わない)

- Python(`tests/`): 営業日と年内受渡(4.1 の確認用の値)、CSV の読み込み(cp932、日付、分配金の調整)、指標の既知の値、スコアが 0〜100 で未来のデータに影響されないこと・価格が下がるとスコアが上がること、ML の学習行が答えの確定した行だけであること・乱数データで `valid: false`、検証の不変条件(価格一定なら差 0、回数と金額、期限を守る、V 字の合成データでスコア戦略が有利)、通知のまたぎ判定と日付判定・標準出力に購読先やラベルが出ないこと・`GITHUB_ACTIONS=true` で dry-run を拒否、偽のデータでのビルドが 5 章のキーをそろえて出すこと、privacy_check が違反の例を見つけること。
- JS(`site/tests/*.test.mjs`、node:test): 計画の確認(6.2 の各項目)、年内受渡の計算(4.1 の確認用の値)、通知設定の JSON に金額が入らないこと。

## 9. 確認コマンド

```
.venv\Scripts\python -m pytest -q
node --test site/tests/
.venv\Scripts\python scripts/privacy_check.py
.venv\Scripts\python -m nbt.build --out site/data     (ネットワークが要る)
.venv\Scripts\python -m http.server -d site 8000      (手元で見る)
```

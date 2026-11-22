# AGENTS.md

NISA 成長投資枠の買い時を参考指標で示す PWA。仕様は `docs/SPEC.md`。

- このリポジトリは public。購入計画、金額、個人名、メールアドレス、手元の絶対パスを、コード・文書・テスト・コミットに入れない(`docs/SPEC.md` の 1 章)。
- ブランチ: `main` はリリース専用(push すると Pages へ配備される)。作業は `dev` か作業ごとのブランチで行う。
- 関連フォルダ: なし。
- 確認コマンド: `.venv\Scripts\python -m pytest -q`、`node --test "tests/js/*.test.mjs"`、`.venv\Scripts\python scripts/privacy_check.py`。
- `site/` の殻(HTML、CSS、JS、アイコン)を変えたら、`site/sw.js` の `VERSION` を上げる(殻はキャッシュ優先なので、上げないと端末に古い画面が残る)。
- 依存の追加は `requirements.txt` に版を固定して書く。サイトに外部ライブラリと外部への通信を足さない。

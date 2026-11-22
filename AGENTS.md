# AGENTS.md

NISA 成長投資枠の買い時を参考指標で示す PWA。仕様は `docs/SPEC.md`。

- このリポジトリは public。購入計画、金額、個人名、メールアドレス、手元の絶対パスを、コード・文書・テスト・コミットに入れない(`docs/SPEC.md` の 1 章)。
- ブランチ: `main` はリリース専用(push すると Pages へ配備される)。作業は `dev` か作業ごとのブランチで行う。
- 関連フォルダ: なし。
- 確認コマンド: `.venv\Scripts\python -m pytest -q`、`node --test site/tests/`、`.venv\Scripts\python scripts/privacy_check.py`。
- 依存の追加は `requirements.txt` に版を固定して書く。サイトに外部ライブラリと外部への通信を足さない。

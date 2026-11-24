import assert from "node:assert/strict";
import test from "node:test";
import { defaults, parseBackup } from "../../site/js/storage.js";

test("案内の設定がない従来のバックアップを読み込める", () => {
  const state = defaults();
  delete state.guide_closed;
  assert.deepEqual(parseBackup(JSON.stringify(state)), state);
});

test("案内は既定で表示され、閉じた状態も再表示した状態も保存できる", () => {
  const state = defaults();
  assert.equal(state.guide_closed, false);
  for (const guide_closed of [true, false]) {
    assert.equal(parseBackup(JSON.stringify({ ...state, guide_closed })).guide_closed, guide_closed);
  }
});

test("案内の設定が文字列など真偽値以外のバックアップを拒否する", () => {
  for (const guide_closed of ["false", null, 0]) {
    assert.throws(() => parseBackup(JSON.stringify({ ...defaults(), guide_closed })), /設定ファイルの形式/);
  }
});

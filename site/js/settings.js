import { copyPayload, payloadHash, publicKeyBytes } from "./push.js";
import { clearState, defaults, parseBackup } from "./storage.js";
import { button, card, el, field, input, paragraph } from "./ui.js";

function exportState(state) {
  const blob = new Blob([JSON.stringify(state, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = el("a", { href: url, download: "nbt-settings.json" });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function pushSection(context) {
  let subscription = null;
  let registration = null;
  const output = el("textarea", { readonly: true, rows: 7, "aria-label": "コピー用の通知設定", hidden: true });
  const status = el("p", { role: "status" });
  const remote = el("p", { class: "notice warning", role: "status", hidden: true });
  const operation = el("p", { role: "status" });
  const rules = context.state.notifications;
  let hashCheck = 0;

  async function refreshHash() {
    const request = ++hashCheck;
    const before = context.state.push_hash;
    if (!before) {
      remote.hidden = true;
      return;
    }
    let matches = false;
    try {
      matches = subscription && before === await payloadHash(copyPayload(subscription, context.state));
    } catch {
      // If hashing is unavailable, ask the user to copy the current configuration again.
    }
    if (request !== hashCheck || before !== context.state.push_hash) return;
    remote.textContent = "通知の設定が古くなっています。購読を確認し、必要に応じて Secret を貼り直してください。";
    remote.hidden = Boolean(matches);
  }

  function applyRules() {
    context.persist();
    output.hidden = true;
    output.value = "";
    refreshHash();
  }

  function checkbox(label, key) {
    const element = input(key, "", { type: "checkbox", checked: rules[key] });
    element.addEventListener("change", () => { rules[key] = element.checked; applyRules(); });
    return field(label, element);
  }

  function numeric(label, key, range, factor = 1) {
    const element = input(key, rules[key] === null ? null : rules[key] * factor, {
      type: "number", min: 0, max: range, step: "any",
    });
    element.addEventListener("change", () => {
      if (!element.checkValidity() || (!element.value && key !== "score_at_least")) {
        element.value = rules[key] === null ? "" : rules[key] * factor;
        return;
      }
      rules[key] = element.value ? element.valueAsNumber / factor : null;
      applyRules();
    });
    return field(label, element);
  }

  const subscribe = button("通知を有効にする", async () => {
    subscribe.disabled = true;
    try {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true, applicationServerKey: publicKeyBytes(context.push.vapid_public_key),
      });
      status.textContent = "この端末で購読しました。「通知の設定をコピー」で GitHub に登録できます。";
    } catch {
      status.textContent = "通知を有効にできませんでした。端末の通知許可やホーム画面から開いているかを確認してください。";
    }
    updateControls();
  }, "primary");

  async function rememberCopy(payload) {
    try {
      context.state.push_hash = await payloadHash(payload);
      context.persist();
      refreshHash();
    } catch {
      operation.textContent += " この環境では変更の検出が使えません。";
    }
  }

  const copy = button("通知の設定をコピー", async () => {
    const payload = copyPayload(subscription, context.state);
    try {
      if (!navigator.clipboard?.writeText) throw new Error();
      await navigator.clipboard.writeText(payload);
      operation.textContent = "コピーしました。PUSH_CONFIG に貼り付けてください。";
      rememberCopy(payload);
    } catch {
      output.value = payload;
      output.hidden = false;
      output.focus();
      output.select();
      operation.textContent = "下の欄からコピーして PUSH_CONFIG に貼り付けてください。";
    }
  });
  output.addEventListener("copy", () => {
    if (output.selectionStart === 0 && output.selectionEnd === output.value.length) rememberCopy(output.value);
  });

  const unsubscribe = button("この端末の購読を解除", async () => {
    try {
      await subscription.unsubscribe();
      subscription = await registration.pushManager.getSubscription();
      status.textContent = subscription ? "購読の解除を確認できませんでした。"
        : "この端末の購読を解除しました。GitHub の Secret からも、この端末の購読を削除してください。";
    } catch {
      status.textContent = "購読を解除できませんでした。";
    }
    output.hidden = true;
    output.value = "";
    updateControls();
  });

  function updateControls() {
    subscribe.disabled = !registration?.pushManager || !context.push?.vapid_public_key || Boolean(subscription);
    copy.disabled = unsubscribe.disabled = !subscription;
    refreshHash();
  }

  updateControls();
  status.textContent = "購読の状態を確認しています。";
  context.serviceWorker.then(async worker => {
    try {
      registration = worker;
      subscription = await registration?.pushManager?.getSubscription() ?? null;
      if (subscription) status.textContent = "この端末は購読済みです。";
      else if (!context.push?.vapid_public_key) {
        status.textContent = "公開鍵がありません。scripts/setup_push.py を実行してから Pages を再生成してください。";
      } else if (!registration?.pushManager) status.textContent = "この環境では Web Push を使えません。";
      else status.textContent = "通知を有効にするには端末の通知許可が必要です。";
    } catch {
      registration = null;
      status.textContent = "購読情報を取得できませんでした。";
    }
    updateControls();
  });

  const repo = context.appConfig?.repo;
  const github = typeof repo === "string" && /^[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+$/.test(repo)
    ? el("a", { href: "https://github.com/" + repo + "/settings/secrets/actions", target: "_blank", rel: "noopener noreferrer" },
      "GitHub の Actions Secrets を開く") : null;
  return card(el("h2", {}, "通知"),
    paragraph("iOS ではホーム画面に追加したアプリから通知を有効にしてください。"),
    el("div", { class: "fields" },
      numeric("通知するスコア（空欄で無効）", "score_at_least", 100),
      numeric("ML の確率がこの値以下（%）", "ml_probability", 100, 100)),
    checkbox("計画に登録した価格・下落率の条件", "plan_prices"),
    checkbox("購入予定日の前日と当日", "plan_dates"),
    checkbox("年内受渡の最終注文日まで5・1国内営業日", "year_end"),
    checkbox("検証で有効な実験モデルの通知", "ml_enabled"),
    status, remote, el("div", { class: "actions" }, subscribe, copy, unsubscribe),
    paragraph("GitHub の Settings → Secrets and variables → Actions → New repository secret で名前を PUSH_CONFIG にし、コピーした設定を貼り付けます。"),
    github, operation, output);
}

export function renderSettings(context) {
  const watch = card(el("h2", {}, "ウォッチする銘柄"));
  for (const fund of context.funds) {
    const control = input("watch", fund.id, { type: "checkbox", checked: context.state.watch.includes(fund.id) });
    watch.append(field(fund.name, control));
    control.addEventListener("change", () => {
      context.state.watch = control.checked ? [...context.state.watch, fund.id] :
        context.state.watch.filter(id => id !== fund.id);
      context.persist();
      context.render();
    });
  }
  if (!context.funds.length) watch.append(paragraph("銘柄データがありません。"));

  const file = input("backup", "", { type: "file", accept: "application/json,.json" });
  const feedback = el("p", { role: "status" });
  file.addEventListener("change", async () => {
    const selected = file.files[0];
    if (!selected) return;
    try {
      const saved = parseBackup(await selected.text());
      if (!confirm("この端末の設定と計画を読み込んだ内容で置き換えますか？")) return;
      context.replaceState(saved);
      context.render();
    } catch {
      feedback.textContent = "設定ファイルを読み込めませんでした。書き出した JSON ファイルを選んでください。";
    } finally {
      file.value = "";
    }
  });
  const clear = button("端末のデータを全削除", () => {
    if (!confirm("この端末のウォッチ、設定、購入計画の保存内容を削除しますか？")) return;
    context.replaceState(defaults(context.latest?.default_watch), clearState());
    context.render();
    context.showDisclaimer();
  }, "danger");

  const sources = context.latest?.sources ?? [];
  return [
    watch, pushSection(context),
    card(el("h2", {}, "この端末のデータ"),
      el("div", { class: "actions" }, button("JSON に書き出す", () => exportState(context.state)), clear),
      field("書き出した JSON を読み込む", file), feedback),
    card(el("h2", {}, "アプリについて"),
      button("注意書きを表示", context.showDisclaimer),
      el("h3", {}, "データ元"),
      sources.length ? el("ul", {}, ...sources.map(source =>
        el("li", {}, el("a", { href: source.url, target: "_blank", rel: "noopener noreferrer" }, source.name))))
        : paragraph("データを取得すると表示します。")),
  ];
}

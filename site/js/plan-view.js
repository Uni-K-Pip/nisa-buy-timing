import { parseDay } from "./calendar.js";
import { allocateBudget, checkPlan } from "./plan.js";
import { button, card, el, field, input, issueList, paragraph, select } from "./ui.js";

const STATUS_LABELS = [
  ["planned", "予定"], ["ordered", "注文済み"], ["executed", "約定済み"], ["cancelled", "取消"],
];
const KINDS = [["index", "指数"], ["nav", "基準価額"]];

function blankRow() {
  return {
    id: crypto.randomUUID(), planned_date: null, amount: null, status: "planned",
    order_date: null, trade_date: null, settle_date: null, note: "",
  };
}

function blankPlan() {
  return {
    id: crypto.randomUUID(), fund_id: "", title: "", year: null, budget: null,
    threshold_score: 70, pull_forward_score: 85, levels: [], drop_rule: null,
    installments: [blankRow()], official_last_order_date: null, nisa_used_this_year: null,
  };
}

function numberField(label, name, value, { min = 0, max, step = 1 } = {}) {
  return field(label, input(name, value, { type: "number", min, max, step, inputmode: step === 1 ? "numeric" : "decimal" }));
}

function dateField(label, name, value) {
  return field(label, input(name, value, { type: "date" }));
}

function readPlan(form, draft) {
  const data = new FormData(form);
  const text = name => String(data.get(name) ?? "").trim();
  const day = name => text(name) || null;
  const num = name => text(name) === "" ? null : Number(text(name));
  const dropKind = text("drop_kind");
  return {
    id: draft.id, fund_id: text("fund_id"), title: text("title"), year: num("year"), budget: num("budget"),
    threshold_score: num("threshold_score") ?? 70, pull_forward_score: num("pull_forward_score") ?? 85,
    official_last_order_date: day("official_last_order_date"), nisa_used_this_year: num("nisa_used_this_year"),
    levels: draft.levels.map((_, i) => ({ kind: text("level_kind_" + i), op: "<=", value: num("level_value_" + i) })),
    drop_rule: dropKind ? { kind: dropKind, reference_value: num("reference_value"), pct: num("drop_pct") } : null,
    installments: draft.installments.map(row => {
      const key = row.id + "_";
      return {
        id: row.id, planned_date: day(key + "planned"), amount: num(key + "amount"), status: text(key + "status"),
        order_date: day(key + "order"), trade_date: day(key + "trade"), settle_date: day(key + "settle"),
        note: text(key + "note"),
      };
    }),
  };
}

function fields(...children) {
  return el("div", { class: "fields" }, ...children);
}

function editor(context, draft) {
  const form = el("form", { class: "card" });
  const messages = el("div", { "aria-live": "polite" });
  const feedback = el("p", { class: "notice", role: "status", hidden: true });
  const plans = context.state.plans;
  const existing = plans.some(plan => plan.id === draft.id);
  const fundItems = [["", "選択してください"], ...context.funds.map(fund => [fund.id, fund.name])];
  if (draft.fund_id && !fundItems.some(([id]) => id === draft.fund_id)) fundItems.push([draft.fund_id, draft.fund_id]);
  const note = text => { feedback.textContent = text; feedback.hidden = false; };

  function showChecks(plan) {
    const fund = context.funds.find(item => item.id === plan.fund_id);
    const issues = checkPlan(plan, { ...context, fund });
    const captions = new Map(plan.installments.map((row, i) => [row.id, (i + 1) + "回目 · "]));
    messages.replaceChildren(issueList(issues.map(issue => ({
      ...issue, text: (captions.get(issue.id) ?? "") + issue.text,
    }))));
    return issues;
  }

  function update(change) {
    const current = readPlan(form, draft);
    change(current);
    context.selection.draft = current;
    context.render();
  }

  function entry(row, i) {
    const key = row.id + "_";
    const status = value => update(current => {
      const item = current.installments.find(target => target.id === row.id);
      item.status = value;
      if (value === "ordered" && !item.order_date) item.order_date = context.today;
    });
    return el("fieldset", {}, el("legend", {}, (i + 1) + "回目"),
      fields(dateField("予定日", key + "planned", row.planned_date),
        numberField("金額（円）", key + "amount", row.amount, { max: Number.MAX_SAFE_INTEGER }),
        field("状態", select(key + "status", STATUS_LABELS, row.status)),
        dateField("注文日", key + "order", row.order_date),
        dateField("約定日（公式画面の値）", key + "trade", row.trade_date),
        dateField("受渡日（公式画面の値）", key + "settle", row.settle_date)),
      field("メモ", el("textarea", { name: key + "note", rows: 2 }, row.note)),
      el("div", { class: "actions" },
        button("注文した", () => status("ordered")), button("約定した", () => status("executed")),
        button("この回を外す", () => update(current => {
          current.installments = current.installments.filter(item => item.id !== row.id);
        }), "danger")));
  }

  const title = draft.title || (existing ? "購入計画" : "新しい購入計画");
  form.append(el("h2", {}, title),
    fields(field("銘柄", select("fund_id", fundItems, draft.fund_id)),
      field("計画名", input("title", draft.title, { maxlength: 100 })),
      numberField("対象年", "year", draft.year, { min: 1900, max: 9999 }),
      numberField("予算（円）", "budget", draft.budget, { max: Number.MAX_SAFE_INTEGER }),
      numberField("検討するスコア", "threshold_score", draft.threshold_score, { max: 100 }),
      numberField("前倒しを検討するスコア", "pull_forward_score", draft.pull_forward_score, { max: 100 }),
      dateField("公式画面で確認した年内最終注文日", "official_last_order_date", draft.official_last_order_date),
      numberField("その年の利用済み成長投資枠（円）", "nisa_used_this_year", draft.nisa_used_this_year,
        { max: Number.MAX_SAFE_INTEGER })),
    paragraph("公式の日付が空欄の場合は推定を使います。利用済み枠には、受渡済みの分を入力してください。", "secondary"),
    el("fieldset", {}, el("legend", {}, "価格の条件"),
      ...draft.levels.map((level, i) => fields(field("対象", select("level_kind_" + i, KINDS, level.kind)),
        numberField("この値以下", "level_value_" + i, level.value, { step: "any" }),
        button("条件を外す", () => update(current => { current.levels.splice(i, 1); }), "danger"))),
      el("div", { class: "actions" }, button("価格の条件を追加", () => update(current => {
        current.levels.push({ kind: "index", op: "<=", value: null });
      }))),
      fields(field("下落率の対象", select("drop_kind", [["", "使用しない"], ...KINDS], draft.drop_rule?.kind ?? "")),
        numberField("基準にする価格", "reference_value", draft.drop_rule?.reference_value, { step: "any" }),
        numberField("下落率（%）", "drop_pct", draft.drop_rule?.pct, { max: 100, step: "any" }))),
    el("h3", {}, "購入予定と記録"),
    el("div", { class: "actions" }, button("回を追加", () => update(current => { current.installments.push(blankRow()); })),
      button("予算を各回に割り振る", () => {
        const current = readPlan(form, draft);
        const active = current.installments.filter(row => row.status !== "cancelled");
        const completed = active.filter(row => row.status !== "planned");
        const remaining = active.filter(row => row.status === "planned");
        const amounts = allocateBudget(current.budget === null ? null :
          current.budget - completed.reduce((total, row) => total + (row.amount ?? 0), 0), remaining.length);
        if (!amounts.length) {
          note("予算と未注文の回を確認してください。");
          return;
        }
        remaining.forEach((row, i) => { row.amount = amounts[i]; });
        context.selection.draft = current;
        context.render();
      })),
    ...draft.installments.map(entry), messages, feedback,
    el("div", { class: "actions" }, el("button", { type: "submit", class: "primary" }, "端末に保存"),
      button("編集を閉じる", () => { context.selection.draft = null; context.render(); }),
      existing ? button("計画を削除", () => {
        if (!confirm("この端末からこの計画を削除しますか？")) return;
        context.state.plans = plans.filter(item => item.id !== draft.id);
        context.selection.draft = null;
        context.persist();
        context.render();
      }, "danger") : null));

  form.addEventListener("change", () => {
    const current = readPlan(form, draft);
    context.selection.draft = current;
    showChecks(current);
  });
  form.addEventListener("submit", event => {
    event.preventDefault();
    const plan = readPlan(form, draft);
    const missingLevel = plan.levels.some(rule => !Number.isFinite(rule.value));
    const drop = plan.drop_rule;
    if (!plan.fund_id || missingLevel || drop && (!Number.isFinite(drop.reference_value) || !Number.isFinite(drop.pct))) {
      note("銘柄を選び、追加した価格条件の値を入力してください。");
      return;
    }
    if (plan.official_last_order_date && (!plan.year || parseDay(plan.official_last_order_date) === null ||
        !plan.official_last_order_date.startsWith(String(plan.year) + "-"))) {
      note("公式の最終注文日は、対象年の日付を入力してください。");
      return;
    }
    if (showChecks(plan).some(issue => issue.type === "error")) {
      note("上のエラーを確認してください。");
      return;
    }
    if (existing) context.state.plans = plans.map(item => item.id === plan.id ? plan : item);
    else context.state.plans.push(plan);
    context.selection.draft = null;
    context.persist();
    context.render();
  });
  showChecks(draft);
  return form;
}

export function renderPlans(context) {
  const edit = plan => {
    context.selection.draft = structuredClone(plan);
    context.render();
  };
  return [
    paragraph("予定と購入記録はこの端末に保存されます。", "secondary"),
    el("div", { class: "actions" }, context.funds.length ?
      button("新しい計画", () => edit(blankPlan()), "primary") : null),
    ...context.state.plans.map(plan => {
      const fund = context.funds.find(item => item.id === plan.fund_id);
      return card(el("h2", {}, plan.title || "購入計画"),
        paragraph((fund?.name ?? plan.fund_id) + (plan.year ? " · " + plan.year + "年" : "")),
        button("この計画を編集", () => edit(plan)));
    }),
    context.selection.draft ? editor(context, context.selection.draft) : null,
  ];
}

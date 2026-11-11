import { renderMarkdown } from "./markdown.js";
import { chartData, extractTables, proportionParts, toCsv } from "./tables.js";
import { fitSegmentLabels, renderBars, renderPie, renderProportion } from "./charts.js";

const chat = document.getElementById("chat");
const form = document.getElementById("form");
const input = document.getElementById("input");
const send = document.getElementById("send");
const hint = document.getElementById("hint");

function loadSession() {
  try { return sessionStorage.getItem("session_id") || undefined; } catch { return undefined; }
}
function saveSession(id) {
  try { id ? sessionStorage.setItem("session_id", id) : sessionStorage.removeItem("session_id"); } catch { /* sem storage */ }
}
let sessionId = loadSession();

function addMessage(kind, content) {
  hint?.remove();
  const el = document.createElement("div");
  el.className = `msg ${kind}`;
  if (typeof content === "string") el.textContent = content;
  else el.append(content);
  chat.append(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

function grow() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
}

function button(label, onClick, title) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  if (title) b.title = title;
  b.addEventListener("click", onClick);
  return b;
}

function downloadCsv(table) {
  const blob = new Blob(["﻿", toCsv(table)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "consulta-tickets.csv";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function printMessage(msg) {
  msg.classList.add("print-target");
  document.body.classList.add("print-one");
  const done = () => {
    msg.classList.remove("print-target");
    document.body.classList.remove("print-one");
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.print();
}

// Mensagem do assistente: texto + visões alternativas (tabela, barras, proporção) quando há tabela nos dados.
function buildAssistant(data) {
  const msg = addMessage("assistant", "");
  const tables = extractTables(data.resposta);
  const charts = tables.map((t) => chartData(t));
  const chartIndex = charts.findIndex(Boolean);
  const chart = chartIndex >= 0 ? charts[chartIndex] : null;
  const chartTable = chart ? tables[chartIndex] : null;

  const views = { texto: () => renderMarkdown(data.resposta) };
  if (tables.length) {
    views.tabela = () => {
      const frag = document.createDocumentFragment();
      for (const t of tables) {
        const wrap = document.createElement("div");
        wrap.className = "table-wrap";
        const table = document.createElement("table");
        const head = table.createTHead().insertRow();
        t.header.forEach((h) => { const th = document.createElement("th"); th.textContent = h; head.append(th); });
        const body = table.createTBody();
        t.rows.forEach((r) => { const tr = body.insertRow(); r.forEach((c) => { tr.insertCell().textContent = c; }); });
        wrap.append(table);
        frag.append(wrap);
      }
      return frag;
    };
  }
  if (chart) {
    views.barras = () => renderBars(chart);
    if (proportionParts(chart)) {
      views.pizza = () => renderPie(chart);
      views.proporcao = () => renderProportion(chart);
    }
  }
  const labels = { texto: "Texto", tabela: "Tabela", barras: "Barras", pizza: "Pizza", proporcao: "Proporção" };

  const toolbar = document.createElement("div");
  toolbar.className = "toolbar";
  const view = document.createElement("div");
  view.className = "view";
  const tabs = {};

  function show(name) {
    view.replaceChildren(views[name]());
    for (const [key, b] of Object.entries(tabs)) b.setAttribute("aria-pressed", String(key === name));
    fitSegmentLabels(view);
  }

  if (Object.keys(views).length > 1) {
    for (const name of Object.keys(views)) {
      tabs[name] = button(labels[name], () => show(name));
      toolbar.append(tabs[name]);
    }
  }
  const actions = document.createElement("span");
  actions.className = "actions";
  if (tables.length) actions.append(button("CSV", () => downloadCsv(chartTable ?? tables[0]), "Baixar a primeira tabela em CSV"));
  actions.append(button("PDF", () => printMessage(msg), "Imprimir ou salvar esta resposta em PDF"));
  toolbar.append(actions);
  msg.replaceChildren(toolbar, view);

  const wanted = data.visualizacaoPreferida;
  const chartWanted = wanted === "pizza" || wanted === "proporcao";
  const initial = wanted && views[wanted] ? wanted : chartWanted && views.barras ? "barras" : "texto";
  show(initial);

  if (data.sugestoes?.length) {
    const chips = document.createElement("div");
    chips.className = "chips";
    for (const s of data.sugestoes) chips.append(button(s, () => { input.value = s; form.requestSubmit(); }));
    msg.append(chips);
  }
  const meta = document.createElement("div");
  meta.className = "meta";
  const tools = data.toolsUtilizadas?.length ? ` · ${[...new Set(data.toolsUtilizadas)].join(", ")}` : "";
  meta.textContent = `${(data.duracaoMs / 1000).toFixed(1)} s${tools}`;
  msg.append(meta);
  chat.scrollTop = chat.scrollHeight;
  return msg;
}

async function ask(pergunta) {
  document.querySelectorAll(".chips").forEach((c) => c.remove());
  addMessage("user", pergunta);
  const pending = addMessage("loading", "Consultando…");
  send.disabled = true;
  try {
    const res = await fetch("/api/ia/consultar-os", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-User-Id": "interface-web" },
      body: JSON.stringify({ pergunta, session_id: sessionId }),
    });
    const data = await res.json().catch(() => ({}));
    pending.remove();
    if (!res.ok) {
      addMessage("error", data.mensagem || `Erro ${res.status} ao consultar.`);
      return;
    }
    sessionId = data.sessionId;
    saveSession(sessionId);
    buildAssistant(data);
  } catch {
    pending.remove();
    addMessage("error", "Não foi possível falar com o servidor.");
  } finally {
    send.disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const pergunta = input.value.trim();
  if (!pergunta || send.disabled) return;
  input.value = "";
  grow();
  ask(pergunta);
});
input.addEventListener("input", grow);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
});
document.querySelectorAll(".example").forEach((b) => b.addEventListener("click", () => {
  input.value = b.textContent;
  form.requestSubmit();
}));
document.getElementById("new-chat").addEventListener("click", () => {
  sessionId = undefined;
  saveSession(undefined);
  chat.replaceChildren();
  input.focus();
});
window.addEventListener("resize", () => document.querySelectorAll(".view").forEach(fitSegmentLabels));
input.focus();

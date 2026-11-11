// Gráficos em HTML/CSS (sem innerHTML). Barras horizontais ordenadas e barra segmentada de proporção.
import { arcPath, formatPercent, pieSlices, proportionParts } from "./tables.js";

const MAX_BARS = 20;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function renderBars(data) {
  const root = el("div", "viz");
  root.setAttribute("role", "group");
  root.setAttribute("aria-label", `Barras: ${data.valueHeader} por ${data.labelHeader}`);
  root.append(el("p", "viz-title", `${data.valueHeader} por ${data.labelHeader.toLowerCase()}`));

  const shown = data.items.slice(0, MAX_BARS);
  const max = Math.max(...shown.map((it) => it.value)) || 1;
  const list = el("div", "bars");
  for (const it of shown) {
    const summary = `${it.label}: ${it.text} (${formatPercent(it.value, data.total)})`;
    const row = el("div", "bar-row");
    row.tabIndex = 0;
    row.title = summary;
    row.setAttribute("aria-label", summary);
    const track = el("div", "bar-track");
    const bar = el("div", "bar");
    bar.style.width = `${(it.value / max) * 100}%`;
    track.append(bar, el("span", "bar-value", it.text));
    row.append(el("span", "bar-label", it.label), track);
    list.append(row);
  }
  root.append(list);
  if (data.items.length > shown.length) {
    root.append(el("p", "viz-note", `+ ${data.items.length - shown.length} itens menores na visão Tabela.`));
  }
  return root;
}

export function renderProportion(data) {
  const parts = proportionParts(data);
  if (!parts) return null;
  const root = el("div", "viz");
  root.setAttribute("role", "group");
  root.setAttribute("aria-label", `Proporção de ${data.valueHeader} por ${data.labelHeader}`);
  root.append(el("p", "viz-title", `Proporção de ${data.valueHeader.toLowerCase()} por ${data.labelHeader.toLowerCase()}`));

  const total = parts.reduce((s, p) => s + p.value, 0);
  const bar = el("div", "seg-bar");
  const legend = el("ul", "legend");
  parts.forEach((p, i) => {
    const slot = p.other ? "other" : `s${i + 1}`;
    const share = formatPercent(p.value, total);
    const summary = `${p.label}: ${p.text} (${share})`;
    const block = el("div", `seg seg-${slot}`);
    block.style.flexGrow = String(p.value);
    block.tabIndex = 0;
    block.title = summary;
    block.setAttribute("aria-label", summary);
    block.append(el("span", "seg-label", share));
    bar.append(block);

    const li = el("li");
    const swatch = el("span", `swatch seg-${slot}`);
    swatch.setAttribute("aria-hidden", "true");
    li.append(swatch, document.createTextNode(p.label));
    legend.append(li);
  });
  root.append(bar, legend);
  return root;
}

// Rótulo que não cabe no bloco some (nunca é cortado); o valor continua na visão Tabela.
export function fitSegmentLabels(root) {
  for (const block of root.querySelectorAll(".seg")) {
    const label = block.querySelector(".seg-label");
    if (!label) continue;
    label.style.visibility = "visible";
    label.style.visibility = block.clientWidth >= label.offsetWidth + 16 ? "visible" : "hidden";
  }
}

const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

// Pizza: no máximo 6 fatias (o resto vira "Outros"), 2px de superfície entre fatias, legenda com valores.
// O percentual só vai dentro da fatia quando ela é grande o bastante; o valor sempre está na legenda.
export function renderPie(data) {
  const parts = proportionParts(data);
  if (!parts) return null;
  const slices = pieSlices(parts);
  const root = el("div", "viz");
  root.setAttribute("role", "group");
  root.setAttribute("aria-label", `Pizza: ${data.valueHeader} por ${data.labelHeader}`);
  root.append(el("p", "viz-title", `${data.valueHeader} por ${data.labelHeader.toLowerCase()}`));

  const wrap = el("div", "pie-wrap");
  const chart = svg("svg", { viewBox: "0 0 200 200", class: "pie", role: "img" });
  chart.setAttribute("aria-label", slices.map((s) => `${s.label}: ${formatPercent(s.value, data.total)}`).join("; "));
  const legend = el("ul", "legend legend-values");

  slices.forEach((s, i) => {
    const slot = s.other ? "other" : `s${i + 1}`;
    const share = formatPercent(s.value, parts.reduce((t, p) => t + p.value, 0));
    const summary = `${s.label}: ${s.text} (${share})`;
    const path = svg("path", { d: arcPath(100, 100, 92, s.start, s.end), class: `slice pie-${slot}`, tabindex: 0 });
    path.setAttribute("aria-label", summary);
    const tip = svg("title");
    tip.textContent = summary;
    path.append(tip);
    chart.append(path);

    if (s.share >= 0.1) {
      const mid = (s.start + s.end) / 2;
      const label = svg("text", {
        x: (100 + 58 * Math.sin(mid)).toFixed(1), y: (100 - 58 * Math.cos(mid)).toFixed(1),
        class: `pie-label pie-${slot}-text`, "text-anchor": "middle", "dominant-baseline": "central",
      });
      label.textContent = share;
      chart.append(label);
    }

    const li = el("li");
    const swatch = el("span", `swatch seg-${slot}`);
    swatch.setAttribute("aria-hidden", "true");
    li.append(swatch, document.createTextNode(`${s.label} · ${s.text} (${share})`));
    legend.append(li);
  });
  wrap.append(chart, legend);
  root.append(wrap);
  return root;
}

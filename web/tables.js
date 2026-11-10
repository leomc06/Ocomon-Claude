// Tabelas Markdown -> dados (CSV, gráficos). Tudo puro, sem DOM: testável em Node.
import { parseMarkdown } from "./markdown.js";

const inlineText = (nodes) => nodes.map((n) => n.v).join("").trim();

export function extractTables(markdown) {
  return parseMarkdown(markdown)
    .filter((b) => b.type === "table")
    .map((b) => ({ header: b.header.map(inlineText), rows: b.rows.map((r) => r.map(inlineText)) }));
}

// "5.274" -> 5274 · "39,7%" -> 39.7 · "1.234,5" -> 1234.5 · texto -> null
export function parseNumber(text) {
  let s = String(text ?? "").trim().replace(/%$/, "").trim();
  if (!s) return null;
  if (/^-?\d{1,3}(\.\d{3})+(,\d+)?$/.test(s)) s = s.replace(/\./g, "").replace(",", ".");
  else if (/^-?\d+(,\d+)?$/.test(s)) s = s.replace(",", ".");
  else if (!/^-?\d+(\.\d+)?$/.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

const isTotalLabel = (s) => /^(total|totais|soma)$/i.test(s.trim());
const isPercentHeader = (s) => /%|percent/i.test(s);

// Primeira coluna de texto = rótulos; primeira coluna numérica (de preferência não-percentual) = valores.
export function chartData(table, { maxRows = 40 } = {}) {
  const { header, rows } = table;
  if (!rows.length || header.length < 2) return null;
  const col = (i) => rows.map((r) => r[i] ?? "");
  const numeric = header.map((_, i) => col(i).every((c) => parseNumber(c) !== null));
  const labelCol = numeric.findIndex((isNum) => !isNum);
  if (labelCol === -1) return null;
  const candidates = header.map((_, i) => i).filter((i) => i !== labelCol && numeric[i]);
  if (!candidates.length) return null;
  const valueCol = candidates.find((i) => !isPercentHeader(header[i])) ?? candidates[0];

  const items = rows
    .filter((r) => !isTotalLabel(r[labelCol] ?? ""))
    .map((r) => ({ label: r[labelCol], text: r[valueCol], value: parseNumber(r[valueCol]) }))
    .filter((it) => it.value !== null && it.value >= 0);
  if (items.length < 2 || items.length > maxRows) return null;
  items.sort((a, b) => b.value - a.value);
  return { labelHeader: header[labelCol], valueHeader: header[valueCol], items, total: items.reduce((s, it) => s + it.value, 0) };
}

export function formatPercent(value, total) {
  if (!total) return "0%";
  return `${(Math.round((value / total) * 1000) / 10).toString().replace(".", ",")}%`;
}

// Barra segmentada: no máximo `maxParts` partes; o resto vira "Outros".
export function proportionParts(data, maxParts = 6) {
  const positive = data.items.filter((it) => it.value > 0);
  if (positive.length < 2) return null;
  if (positive.length <= maxParts) return positive.map((it) => ({ ...it, other: false }));
  const head = positive.slice(0, maxParts - 1).map((it) => ({ ...it, other: false }));
  const rest = positive.slice(maxParts - 1);
  const sum = rest.reduce((s, it) => s + it.value, 0);
  return [...head, { label: "Outros", text: String(sum).replace(/\B(?=(\d{3})+(?!\d))/g, "."), value: sum, other: true }];
}

export function toCsv(table, sep = ";") {
  const cell = (raw) => {
    let s = String(raw ?? "");
    // Evita que o Excel execute fórmulas vindas do texto de um ticket.
    if (/^[=+\-@\t\r]/.test(s) && parseNumber(s) === null) s = `'${s}`;
    return /[";\n\r]/.test(s) || s.includes(sep) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [table.header, ...table.rows].map((r) => r.map(cell).join(sep)).join("\r\n");
}

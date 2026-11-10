import test from "node:test";
import assert from "node:assert/strict";
import { chartData, extractTables, formatPercent, parseNumber, proportionParts, toCsv } from "../../web/tables.js";

const MD = `Resumo:

| Área | Abertos | % |
|---|---|---|
| WEB | 27 | 39,7% |
| Suporte | 24 | 35,3% |
| Gestão | 9 | 13,2% |
| **Total** | 60 | 100% |
`;

test("parseNumber entende o formato brasileiro", () => {
  assert.equal(parseNumber("5.274"), 5274);
  assert.equal(parseNumber("39,7%"), 39.7);
  assert.equal(parseNumber("1.234,5"), 1234.5);
  assert.equal(parseNumber("-3"), -3);
  assert.equal(parseNumber("12"), 12);
  for (const bad of ["", "abc", "#4830", "1.2.3", "2026-10-01", null, "—"]) assert.equal(parseNumber(bad), null, String(bad));
});

test("extractTables lê cabeçalho e linhas como texto puro", () => {
  const [t] = extractTables(MD);
  assert.deepEqual(t.header, ["Área", "Abertos", "%"]);
  assert.equal(t.rows.length, 4);
  assert.equal(t.rows[3][0], "Total");
});

test("chartData usa a 1ª coluna de texto e a 1ª numérica não percentual; ignora Total", () => {
  const d = chartData(extractTables(MD)[0]);
  assert.equal(d.valueHeader, "Abertos");
  assert.deepEqual(d.items.map((i) => [i.label, i.value]), [["WEB", 27], ["Suporte", 24], ["Gestão", 9]]);
  assert.equal(d.total, 60);
});

test("chartData devolve null quando não há o que plotar", () => {
  assert.equal(chartData({ header: ["Campo", "Valor"], rows: [["Status", "Encerrada"], ["Área", "WEB"]] }), null);
  assert.equal(chartData({ header: ["Área", "Qtd"], rows: [["WEB", "3"]] }), null);
  assert.equal(chartData({ header: ["Qtd", "Outro"], rows: [["1", "2"], ["3", "4"]] }), null);
  assert.equal(chartData({ header: ["A"], rows: [["x"]] }), null);
  assert.equal(extractTables("sem tabela aqui").length, 0);
});

test("chartData ordena do maior para o menor", () => {
  const d = chartData({ header: ["Status", "Qtd"], rows: [["a", "1"], ["b", "10"], ["c", "5"]] });
  assert.deepEqual(d.items.map((i) => i.label), ["b", "c", "a"]);
});

test("proportionParts: até 6 partes, resto vira Outros", () => {
  const rows = ["a", "b", "c", "d", "e", "f", "g", "h"].map((l, i) => [l, String(100 - i * 10)]);
  const d = chartData({ header: ["X", "Qtd"], rows });
  const parts = proportionParts(d);
  assert.equal(parts.length, 6);
  assert.equal(parts[5].label, "Outros");
  assert.equal(parts[5].other, true);
  assert.equal(parts.reduce((s, p) => s + p.value, 0), d.total);
  assert.equal(proportionParts({ items: [{ label: "x", text: "1", value: 1 }] }), null);
});

test("formatPercent usa vírgula", () => {
  assert.equal(formatPercent(27, 68), "39,7%");
  assert.equal(formatPercent(1, 0), "0%");
  assert.equal(formatPercent(1, 2), "50%");
});

test("toCsv: separador ;, aspas e proteção contra fórmula", () => {
  const csv = toCsv({ header: ["Assunto", "Qtd"], rows: [['Ola; "mundo"', "5.274"], ["=HYPERLINK(\"x\")", "-3"], ["+cmd", "2"]] });
  const lines = csv.split("\r\n");
  assert.equal(lines[0], "Assunto;Qtd");
  assert.equal(lines[1], '"Ola; ""mundo""";5.274');
  assert.equal(lines[2], "\"'=HYPERLINK(\"\"x\"\")\";-3");
  assert.equal(lines[3], "'+cmd;2");
});

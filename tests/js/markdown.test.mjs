import test from "node:test";
import assert from "node:assert/strict";
import { parseMarkdown, parseInline } from "../../web/markdown.js";

test("inline: negrito, código e itálico", () => {
  assert.deepEqual(parseInline("a **b** `c` *d* e"), [
    { t: "text", v: "a " }, { t: "strong", v: "b" }, { t: "text", v: " " }, { t: "code", v: "c" },
    { t: "text", v: " " }, { t: "em", v: "d" }, { t: "text", v: " e" },
  ]);
});

test("tabela com separador", () => {
  const [t] = parseMarkdown("| Área | Abertos |\n|---|---|\n| WEB | 27 |\n| Suporte | 24 |");
  assert.equal(t.type, "table");
  assert.equal(t.header.length, 2);
  assert.equal(t.rows.length, 2);
  assert.deepEqual(t.rows[0][1], [{ t: "text", v: "27" }]);
});

test("listas, títulos e parágrafos", () => {
  const b = parseMarkdown("## Título\n\ntexto\ncontinua\n\n- um\n- dois\n\n1. a\n2. b");
  assert.deepEqual(b.map((x) => x.type), ["heading", "paragraph", "list", "list"]);
  assert.equal(b[1].inline[0].v, "texto continua");
  assert.equal(b[2].ordered, false);
  assert.equal(b[3].ordered, true);
});

test("bloco de código preserva o texto", () => {
  const [p] = parseMarkdown("```\nx = 1\n  y\n```");
  assert.deepEqual(p, { type: "pre", text: "x = 1\n  y" });
});

test("HTML cru vira texto, nunca elemento", () => {
  const [p] = parseMarkdown("<img src=x onerror=alert(1)> **ok**");
  assert.ok(p.inline.every((n) => ["text", "strong"].includes(n.t)));
  assert.match(p.inline[0].v, /<img/);
});

test("entrada vazia ou nula", () => {
  assert.deepEqual(parseMarkdown(""), []);
  assert.deepEqual(parseMarkdown(null), []);
});

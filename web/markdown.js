// Markdown mínimo (negrito, itálico, código, títulos, listas, tabelas) sem innerHTML.
// parseMarkdown é puro (testável em Node); renderMarkdown monta DOM com textContent.

export function parseInline(text) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push({ t: "text", v: text.slice(last, m.index) });
    const tok = m[0];
    if (tok.startsWith("**")) out.push({ t: "strong", v: tok.slice(2, -2) });
    else if (tok.startsWith("`")) out.push({ t: "code", v: tok.slice(1, -1) });
    else out.push({ t: "em", v: tok.slice(1, -1) });
    last = m.index + tok.length;
  }
  if (last < text.length) out.push({ t: "text", v: text.slice(last) });
  return out;
}

const splitRow = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const isSeparator = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);

export function parseMarkdown(src) {
  const lines = String(src ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }

    if (line.trim().startsWith("```")) {
      const code = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i++]);
      i += 1;
      blocks.push({ type: "pre", text: code.join("\n") });
      continue;
    }

    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { blocks.push({ type: "heading", level: h[1].length, inline: parseInline(h[2]) }); i += 1; continue; }

    if (line.includes("|") && i + 1 < lines.length && isSeparator(lines[i + 1])) {
      const header = splitRow(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(splitRow(lines[i++]));
      blocks.push({
        type: "table",
        header: header.map(parseInline),
        rows: rows.map((r) => r.map(parseInline)),
      });
      continue;
    }

    const li = line.match(/^\s*([-*]|\d+[.)])\s+(.*)$/);
    if (li) {
      const ordered = /\d/.test(li[1]);
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(/^\s*([-*]|\d+[.)])\s+(.*)$/);
        if (!m || /\d/.test(m[1]) !== ordered) break;
        items.push(parseInline(m[2]));
        i += 1;
      }
      blocks.push({ type: "list", ordered, items });
      continue;
    }

    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*([-*]|\d+[.)])\s|```)/.test(lines[i])
      && !(lines[i].includes("|") && i + 1 < lines.length && isSeparator(lines[i + 1]))) {
      para.push(lines[i++].trim());
    }
    blocks.push({ type: "paragraph", inline: parseInline(para.join(" ")) });
  }
  return blocks;
}

function appendInline(parent, nodes) {
  for (const n of nodes) {
    if (n.t === "text") parent.append(document.createTextNode(n.v));
    else {
      const el = document.createElement(n.t);
      el.textContent = n.v;
      parent.append(el);
    }
  }
}

export function renderMarkdown(src) {
  const root = document.createDocumentFragment();
  for (const b of parseMarkdown(src)) {
    let el;
    if (b.type === "heading") { el = document.createElement(`h${Math.min(b.level + 2, 6)}`); appendInline(el, b.inline); }
    else if (b.type === "paragraph") { el = document.createElement("p"); appendInline(el, b.inline); }
    else if (b.type === "pre") { el = document.createElement("pre"); el.textContent = b.text; }
    else if (b.type === "list") {
      el = document.createElement(b.ordered ? "ol" : "ul");
      for (const item of b.items) { const li = document.createElement("li"); appendInline(li, item); el.append(li); }
    } else if (b.type === "table") {
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      const table = document.createElement("table");
      const head = table.createTHead().insertRow();
      for (const c of b.header) { const th = document.createElement("th"); appendInline(th, c); head.append(th); }
      const body = table.createTBody();
      for (const r of b.rows) {
        const tr = body.insertRow();
        for (const c of r) { const td = tr.insertCell(); appendInline(td, c); }
      }
      wrap.append(table);
      el = wrap;
    }
    root.append(el);
  }
  return root;
}

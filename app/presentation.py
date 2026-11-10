"""Apresentação: visão pedida na pergunta, sugestões de refinamento e nota de contexto do histórico."""

import json
import re

from app.catalog import normalize_for_match

# (visão, padrão) sobre o texto sem acento. Vence o termo que aparece primeiro na pergunta.
_VIEWS = [
    ("proporcao", re.compile(r"\b(pizza|pizzas|donut|rosca|setores|proporcao|proporcoes)\b")),
    ("barras", re.compile(r"\b(grafico|graficos|barras?|plote|plotar)\b")),
    ("tabela", re.compile(r"\b(tabela|tabelas|tabular)\b")),
]


def detect_visualization(question: str) -> str | None:
    """'tabela', 'barras' ou 'proporcao' quando a pergunta pede explicitamente; senão None."""
    text = normalize_for_match(question)
    found = [(m.start(), view) for view, pattern in _VIEWS if (m := pattern.search(text))]
    return min(found)[1] if found else None


_DATA_TOOLS = {"listar_tickets", "listar_tickets_vencidos", "buscar_tickets_por_texto", "resumo_tickets",
               "resumo_operacional_tickets"}
_REGROUP = {"status": "prioridade", "prioridade": "área", "area": "operador", "operador": "área",
            "departamento": "área", "cliente": "área"}


def build_suggestions(calls: list[dict], limit: int = 4) -> list[str]:
    """Perguntas de acompanhamento a partir da última consulta de dados (chips da interface)."""
    last = next((c for c in reversed(calls)
                 if c["name"] in _DATA_TOOLS and not c.get("error") and c.get("meta", {}).get("encontrado") is not False),
                None)
    if last is None:
        return []
    args, meta = last["args"], last.get("meta", {})
    out: list[str] = []
    if (meta.get("paginas") or 1) > (meta.get("pagina") or 1):
        out.append("Mostrar a próxima página")
    if not args.get("situacao"):
        out += ["Desses, só os abertos", "Desses, só os fechados"]
    elif args["situacao"] != "aberto":
        out.append("Desses, só os abertos")
    if not (args.get("data_inicio") or args.get("data_fim")):
        out.append("Desses, só os do último mês")
    if last["name"] == "resumo_tickets":
        target = _REGROUP.get(args.get("agrupar_por"))
        if target:
            out.append(f"Agrupe por {target}")
    elif last["name"] == "listar_tickets" and not args.get("area"):
        out.append("Quantos são por área?")
    return out[:limit]


def history_note(calls: list[dict], max_chars: int = 900) -> str:
    """Rodapé interno do histórico: quais consultas a resposta fez, para perguntas de acompanhamento."""
    if not calls:
        return ""
    parts = [f"{c['name']}({json.dumps(c['args'], ensure_ascii=False, separators=(',', ':'))[:300]})" for c in calls]
    return ("\n\n[Consultas desta resposta (contexto interno, não repita ao usuário): " + "; ".join(parts))[:max_chars] + "]"

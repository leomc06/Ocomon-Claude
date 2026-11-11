import pytest

from app.presentation import build_suggestions, detect_visualization, history_note


@pytest.mark.parametrize("q,expected", [
    ("Quantos tickets por área? Quero em gráfico", "barras"),
    ("mostre em um gráfico de barras", "barras"),
    ("me dá uma pizza dos status", "pizza"),
    ("mostre em rosca", "pizza"),
    ("qual a proporção por área?", "proporcao"),
    ("Liste os abertos em tabela", "tabela"),
    ("em TABELA e depois gráfico", "tabela"),
    ("em gráfico ou em tabela?", "barras"),
    ("Quantos tickets abertos temos?", None),
    ("tabelado", None),
])
def test_detect_visualization(q, expected):
    assert detect_visualization(q) == expected


def call(name, args=None, meta=None, error=False):
    return {"name": name, "args": args or {}, "meta": meta or {}, "error": error}


def test_suggestions_for_listing_with_more_pages():
    s = build_suggestions([call("listar_tickets", {"area": "WEB"}, {"pagina": 1, "paginas": 3})])
    assert s[0] == "Mostrar a próxima página"
    assert "Desses, só os abertos" in s and len(s) <= 4
    assert "Quantos são por área?" not in s  # já filtrado por área


def test_suggestions_skip_applied_filters_and_regroup():
    s = build_suggestions([call("resumo_tickets", {"agrupar_por": "area", "situacao": "aberto", "data_inicio": "2026-10-01"})])
    assert s == ["Agrupe por operador"]
    s = build_suggestions([call("resumo_tickets", {"agrupar_por": "status", "situacao": "fechado"})])
    assert "Desses, só os fechados" not in s and "Agrupe por prioridade" in s


def test_suggestions_ignore_errors_not_found_and_non_data_tools():
    assert build_suggestions([]) == []
    assert build_suggestions([call("listar_catalogo", {"tipo": "areas"})]) == []
    assert build_suggestions([call("listar_tickets", error=True)]) == []
    assert build_suggestions([call("listar_tickets", meta={"encontrado": False})]) == []
    # usa a última consulta de dados válida
    s = build_suggestions([call("listar_tickets", {"area": "WEB"}), call("listar_catalogo")])
    assert s


def test_history_note():
    assert history_note([]) == ""
    note = history_note([call("listar_tickets", {"area": "WEB", "limite": 20}), call("resumo_tickets", {"agrupar_por": "area"})])
    assert note.startswith("\n\n[Consultas desta resposta") and 'listar_tickets({"area":"WEB","limite":20})' in note
    assert note.endswith("]") and len(history_note([call("x", {"a": "y" * 5000})])) <= 900 + 1

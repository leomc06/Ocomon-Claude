from app.catalog import normalize_for_match, resolve_name

USERS = [
    {"id": 1, "name": "Ana Paula"},
    {"id": 2, "name": "Mariana Souza"},
    {"id": 3, "name": "Luana Sabará"},
    {"id": 4, "name": "Carlos Eduardo"},
]


def test_normalize():
    assert normalize_for_match("  Supercomputação. ") == "supercomputacao"
    assert normalize_for_match("Reservado   para  operador") == "reservado para operador"
    assert normalize_for_match("Gest&atilde;o") == "gestao"
    assert normalize_for_match(None) == ""


def test_exact_wins_over_substring():
    items = [{"id": 1, "name": "Web"}, {"id": 2, "name": "Web Design"}]
    assert resolve_name(items, "web").id == 1


def test_unique_anchored_substring():
    r = resolve_name(USERS, "carlos")
    assert r.id == 4 and r.canonical_name == "Carlos Eduardo"


def test_unique_mid_word_substring_is_discarded():
    # "sabar" só aparece ancorado em Luana Sabará; "uana" cai no meio de palavra
    assert resolve_name(USERS, "uana").not_found
    assert resolve_name(USERS, "sabar").id == 3


def test_ambiguous_lists_candidates():
    r = resolve_name(USERS, "ana")
    assert r.not_found and r.ambiguous
    assert set(r.candidates) == {"Ana Paula", "Mariana Souza", "Luana Sabará"}
    assert "ambíguo" in r.describe("operador", "ana")


def test_gender_suffix_fallback():
    items = [{"id": 9, "name": "ENCERRADA"}]
    assert resolve_name(items, "encerrado").id == 9


def test_not_found_and_none():
    assert resolve_name(USERS, "zzz").describe("operador", "zzz") == 'operador "zzz" não encontrado'
    r = resolve_name(USERS, None)
    assert not r.not_found and r.id is None and r.describe("x", "y") is None


def test_frozen_only_counts_open_tickets():
    from app.catalog import is_frozen_open

    assert is_frozen_open({"is_frozen": True, "status": "EM ATENDIMENTO", "closure_date": None})
    assert not is_frozen_open({"is_frozen": True, "status": "ENCERRADA", "closure_date": "2026-01-01 10:00:00"})
    assert not is_frozen_open({"is_frozen": True, "status": "CANCELADO", "closure_date": None})
    assert not is_frozen_open({"is_frozen": False, "status": "EM ATENDIMENTO", "closure_date": None})
    assert not is_frozen_open({"status": "EM ATENDIMENTO"})

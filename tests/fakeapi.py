"""API de tickets falsa (respx) com filtros, paginação e catálogos, para testar as tools."""

import httpx
import respx

BASE = "http://api.test"

STATUSES = [{"id": 1, "name": "Aberta"}, {"id": 2, "name": "Em Atendimento"},
            {"id": 3, "name": "Encerrada"}, {"id": 4, "name": "CANCELADO"}]
AREAS = [{"id": 10, "name": "WEB"}, {"id": 11, "name": "Suporte"}]
DEPTS = [{"id": 20, "name": "Governança"}, {"id": 21, "name": "Financeiro"}]
USERS = [{"id": 30, "name": "Ana Paula", "login": "ana"}, {"id": 31, "name": "Carlos Eduardo", "login": "carlos"},
         {"id": 32, "name": "Mariana Souza", "login": "mari"}]
PRIORITIES = [{"id": 1, "name": "Baixa"}, {"id": 2, "name": "Alta"}, {"id": 3, "name": "Urgente"}]


def ticket(n, opened, status, area, operator, priority="Baixa", client="Fábio Moreira", closed=None,
           frozen=False, issue="Problema", description="descrição"):
    sid = {s["name"]: s["id"] for s in STATUSES}[status]
    oid = {u["name"]: u["id"] for u in USERS}.get(operator, 0)
    return {"number": n, "opening_date": opened, "closure_date": closed, "status": status, "status_id": sid,
            "area": area, "operator": operator, "operator_id": oid, "priority": priority,
            "contact_name": client, "issue": issue, "description": description, "is_frozen": frozen}


TICKETS = [  # já em ordem decrescente de abertura, como a API real
    ticket(9, "2026-11-01 10:00:00", "Aberta", "WEB", "Ana Paula", "Alta", issue="Impressora parada", description="a impressora não liga"),
    ticket(8, "2026-10-20 09:00:00", "Em Atendimento", "Suporte", "Carlos Eduardo", "Urgente", client="Luana Sabará", frozen=True),
    ticket(7, "2026-10-10 09:00:00", "Encerrada", "WEB", "Ana Paula", closed="2026-10-12 10:00:00", frozen=True),
    ticket(6, "2026-09-30 09:00:00", "CANCELADO", "WEB", "Carlos Eduardo"),
    ticket(5, "2026-09-01 09:00:00", "Aberta", "Suporte", "", "Alta", client="fabio moreira"),
    ticket(4, "2026-08-01 09:00:00", "Encerrada", "Suporte", "Mariana Souza", closed="2026-08-05 10:00:00", client="Ana Lima"),
]
LIFETIMES = {9: {"result_sla_response": 4, "result_sla_solution": 1}, 7: {"result_sla_response": 1, "result_sla_solution": 4},
             8: {"result_sla_response": 1, "result_sla_solution": 1}}


def install(tickets=None):
    data = TICKETS if tickets is None else tickets
    calls = {"list": 0, "detail": 0}

    def list_handler(request):
        calls["list"] += 1
        h = request.headers
        rows = [t for t in data
                if (not h.get("status") or t["status_id"] == int(h["status"]))
                and (not h.get("area") or {a["name"]: a["id"] for a in AREAS}[t["area"]] == int(h["area"]))
                and (not h.get("operator") or t["operator_id"] == int(h["operator"]))]
        if not rows and (h.get("status") or h.get("area") or h.get("operator") or h.get("department")):
            return httpx.Response(400, json={"errors": [{"message": "nada", "type": "not_found"}]})
        limit, page = int(h.get("limit", 10)), int(h.get("page", 1))
        pages = max(-(-len(rows) // limit), 1)
        return httpx.Response(200, json={"results": len(rows), "page": page, "pages": pages,
                                          "tickets": rows[(page - 1) * limit: page * limit]})

    def detail_handler(request):
        calls["detail"] += 1
        n = int(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, json={"number": n, "lifetime": LIFETIMES.get(n, {})})

    respx.get(f"{BASE}/tickets").mock(side_effect=list_handler)
    respx.get(url__regex=rf"{BASE}/tickets/\d+").mock(side_effect=detail_handler)
    for name, items in [("areas", AREAS), ("statuses", STATUSES), ("departments", DEPTS), ("users", USERS),
                        ("priorities", PRIORITIES)]:
        respx.get(f"{BASE}/meta/{name}").mock(return_value=httpx.Response(200, json={name: items}))
    return calls

"""Casos reais contra o servidor em execução (usa a API do Claude e a API de tickets: gasta tokens).

    python scripts/integration.py            # só o caso 1
    python scripts/integration.py 7          # um caso específico
    python scripts/integration.py all        # a suíte inteira
    python scripts/integration.py 7 --url http://127.0.0.1:3100

O servidor precisa estar no ar (`python -m app.main`). Só usa a biblioteca padrão.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

CATALOGO = "listar_catalogo"

# (pergunta, tools aceitas — ao menos uma delas deve ser usada —, verificação extra opcional)
CASES = [
    ("Me fale sobre o ticket 4830", {"buscar_ticket_por_numero"}, None),
    ("Liste os tickets da área WEB", {"listar_tickets"}, None),
    ("Liste os tickets com status Encerrada", {"listar_tickets"}, None),
    ("Quais tickets estão congelados?", {"listar_tickets", "resumo_tickets"}, None),
    ("Quantos tickets temos por status?", {"resumo_tickets"}, None),
    ("Quantos tickets temos por prioridade?", {"resumo_tickets"}, None),
    ("Quantos tickets abertos temos por área? Quero em gráfico", {"resumo_tickets"},
     lambda d: d["visualizacaoPreferida"] == "barras" and "|" in d["resposta"]),
    ("Quais são as áreas cadastradas?", {CATALOGO}, None),
    ("Quais são as prioridades cadastradas?", {CATALOGO}, None),
    ("Quais são os canais de entrada?", {CATALOGO}, None),
    ("Quais são os status possíveis?", {CATALOGO}, None),
    ("Quais são os departamentos?", {CATALOGO}, None),
    ("Quais são os usuários do sistema?", {CATALOGO}, None),
    ("Cancele o ticket 4830.", set(), lambda d: re.search(r"somente consultas|só faz consultas", d["resposta"], re.I) is not None),
    ("Compare a carga do Fábio Gali com a do Cesar Augusto de Mello", {"analisar_carga_operador"},
     lambda d: d["quantidadeChamadas"] >= 2),
    ("Quais tickets estão com o SLA vencido?", {"listar_tickets_vencidos"}, None),
]


def ask(url: str, question: str) -> dict:
    req = urllib.request.Request(
        f"{url}/api/ia/consultar-os",
        data=json.dumps({"pergunta": question}).encode(),
        headers={"Content-Type": "application/json", "X-User-Id": "teste-integracao"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Servidor inacessível em {url} ({e.reason}). Suba com: python -m app.main")


def run_case(url: str, number: int) -> bool:
    question, accepted, extra = CASES[number - 1]
    data = ask(url, question)
    used = set(data["toolsUtilizadas"])
    problems = []
    if accepted and not used & accepted:
        problems.append(f"tools {sorted(used) or '[]'} não incluem nenhuma de {sorted(accepted)}")
    if not accepted and used:
        problems.append(f"não devia chamar tools, chamou {sorted(used)}")
    if not data["resposta"].strip():
        problems.append("resposta vazia")
    if extra and not extra(data):
        problems.append("verificação extra falhou")
    print(f"[{'OK' if not problems else 'FALHA'}] {number:>2}. {question}  ({data['duracaoMs']} ms, tools: {sorted(used) or '-'})")
    for p in problems:
        print(f"      - {p}")
    if problems:
        print("      resposta:", data["resposta"][:300].replace("\n", " "))
    return not problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case", nargs="?", default="1", help="número do caso (1-%d) ou 'all'" % len(CASES))
    parser.add_argument("--url", default="http://127.0.0.1:3100")
    args = parser.parse_args()
    numbers = range(1, len(CASES) + 1) if args.case == "all" else [int(args.case)]
    if any(not 1 <= n <= len(CASES) for n in numbers):
        parser.error(f"caso fora de 1-{len(CASES)}")
    results = [run_case(args.url.rstrip("/"), n) for n in numbers]
    print(f"\n{sum(results)}/{len(results)} casos ok")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

# ocomon-claude

Perguntas em linguagem natural sobre os tickets do OcoMon. Python + API do Claude: o modelo escolhe as
ferramentas (tool use), lê os resultados e redige a resposta. É uma reescrita do zero do projeto
`mcp-teste-llm2-tickets` (Node), que não é alterado por este.

Somente leitura: nenhuma ferramenta cria, altera ou fecha tickets.

## Rodando

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp .env.example .env        # preencha ANTHROPIC_API_KEY e TICKETS_API_*
.venv/bin/python -m app.main            # http://127.0.0.1:3100
.venv/bin/python -m app.cli "Me fale sobre o ticket 4830"   # sem servidor, pelo terminal
```

## Configuração (`.env`)

| Variável | Para quê |
|---|---|
| `ANTHROPIC_API_KEY` | Obrigatória; o servidor não sobe sem ela. |
| `ANTHROPIC_MODEL` | Padrão `claude-haiku-5-5`. |
| `ANTHROPIC_EFFORT` | Opcional (`low`…`max`); vazio usa o padrão do modelo. |
| `ANTHROPIC_TIMEOUT_MS` | Tempo de cada chamada ao Claude. |
| `TICKETS_API_BASE_URL` / `_TOKEN` / `_LOGIN` / `_APP` | Acesso à API HTTP de tickets. |
| `TICKETS_API_TIMEOUT_MS`, `_METADATA_CACHE_TTL_MS`, `_FAN_OUT_CONCURRENCY` | Ajustes do cliente da API. |
| `AGENT_HOST` (127.0.0.1), `AGENT_PORT` (3100) | Onde o servidor escuta. |
| `AGENT_REQUEST_TIMEOUT_MS`, `AGENT_MAX_CONCURRENT_REQUESTS` | Tempo máximo e consultas simultâneas. |
| `AGENT_RATE_LIMIT_WINDOW_MS`, `AGENT_RATE_LIMIT_MAX_REQUESTS` | Limite por IP. |

## Como funciona

```
pergunta ──► POST /api/ia/consultar-os ──► Agent (app/agent.py)
                                            └─ loop: Claude ─► tool_use ─► app/tools/* ─► API de tickets
                                                     ▲              │ tool_result
                                                     └──────────────┘  (até responder em texto)
```

- `app/tickets_api.py` — cliente da API (retry, páginas em paralelo, cache de catálogos e de consultas).
- `app/catalog.py` — resolução de nomes (exato, parcial ancorado, variação de gênero; ambíguo lista candidatos) e regras de negócio (aberto = sem fechamento e não cancelado).
- `app/tools/` — as ferramentas: `listar_catalogo`, `buscar_usuarios_por_nome`, `buscar_ticket_por_numero`,
  `listar_tickets`, `listar_tickets_vencidos`, `buscar_tickets_por_texto`, `resumo_tickets`,
  `resumo_operacional_tickets`, `analisar_carga_operador`, `analisar_atividade_cliente`.
  Cada uma declara os argumentos com pydantic; o schema enviado ao Claude sai do mesmo modelo.
- `app/prompts.py` — instruções em português (somente leitura, dados só das ferramentas, datas relativas).
- `app/presentation.py` — visão pedida na pergunta (tabela/barras/proporção) e chips de refinamento.
- `app/main.py` — FastAPI, limites, auditoria (uma linha JSON por requisição), cabeçalhos de segurança.
- `web/` — chat sem build: Markdown próprio (sem `innerHTML`), visões Texto/Tabela/Barras/Proporção,
  CSV, PDF (impressão da resposta) e chips.

Decisões: o texto de um ticket é tratado como dado (nunca instrução); a conversa guarda só pergunta + resposta
(e, num rodapé interno, os filtros usados) para perguntas de acompanhamento; "pizza" vira barra segmentada de
proporção e gráficos usam a paleta validada da skill `dataviz`.

## Testes

```bash
.venv/bin/pytest -q                                              # Python, tudo mockado
node --test tests/js/markdown.test.mjs tests/js/tables.test.mjs  # frontend (funções puras)
.venv/bin/python scripts/integration.py [N|all]                  # real: gasta tokens; sem argumento roda só o caso 1
```

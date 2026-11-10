"""CLI mínimo: `python -m app.cli "pergunta"` ou, sem argumento, conversa interativa."""

import asyncio
import sys

from app.agent import Agent
from app.config import get_settings
from app.tickets_api import TicketsApiClient


async def main(argv: list[str]) -> None:
    s = get_settings()
    if not s.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY não definida no .env")
    tickets = TicketsApiClient.from_settings(s)
    agent = Agent(s, tickets)
    history: list[dict] = []
    try:
        questions = [" ".join(argv)] if argv else None
        while True:
            if questions is not None:
                if not questions:
                    break
                q = questions.pop(0)
            else:
                try:
                    q = input("> ").strip()
                except EOFError:
                    break
                if not q:
                    continue
            r = await agent.ask(q, history)
            history = r.history
            print(r.answer)
            print(
                f"\n[{r.duration_ms} ms | tools: {', '.join(r.tools_used) or '-'} | "
                f"tokens in/out/cache: {r.input_tokens}/{r.output_tokens}/{r.cache_read_tokens}]\n",
                file=sys.stderr,
            )
    finally:
        await tickets.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))

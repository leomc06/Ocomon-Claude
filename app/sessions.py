import time
from typing import Callable

MAX_HISTORY_MESSAGES = 20  # 10 perguntas+respostas


class SessionStore:
    """Histórico de conversa em memória (só pergunta + resposta final de cada turno)."""

    def __init__(self, ttl_s: float = 1800, max_sessions: int = 500, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_s
        self._max = max_sessions
        self._clock = clock
        self._data: dict[str, tuple[float, list[dict]]] = {}

    def get(self, session_id: str) -> list[dict]:
        entry = self._data.get(session_id)
        if entry is None or self._clock() - entry[0] > self._ttl:
            self._data.pop(session_id, None)
            return []
        return list(entry[1])

    def put(self, session_id: str, history: list[dict]) -> None:
        now = self._clock()
        if session_id not in self._data and len(self._data) >= self._max:
            expired = [k for k, (t, _) in self._data.items() if now - t > self._ttl]
            for k in expired or [min(self._data, key=lambda k: self._data[k][0])]:
                del self._data[k]
        trimmed = history[-MAX_HISTORY_MESSAGES:]
        while trimmed and trimmed[0]["role"] != "user":  # o histórico tem de começar por uma pergunta
            trimmed = trimmed[1:]
        self._data[session_id] = (now, trimmed)

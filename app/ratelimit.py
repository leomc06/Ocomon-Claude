import time
from collections import defaultdict, deque
from typing import Callable


class SlidingWindowLimiter:
    """Limite de requisições por chave (IP) numa janela deslizante."""

    def __init__(self, window_s: float, max_requests: int, clock: Callable[[], float] = time.monotonic):
        self._window = window_s
        self._max = max_requests
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> float:
        """0 se liberado (e registra o acesso); senão, segundos até poder tentar de novo."""
        now = self._clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._max:
            return max(self._window - (now - hits[0]), 0.001)
        hits.append(now)
        if len(self._hits) > 10_000:  # evita crescer sem limite com muitos IPs
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self._window]:
                del self._hits[k]
        return 0

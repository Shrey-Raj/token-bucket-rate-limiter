from app.config import settings
import time, math, logging

logger = logging.getLogger(__name__)

class CircuitBreaker:
    """
    Per-process circuit breaker for Redis.

    CLOSED    -> normal; Redis is called.
    OPEN      -> Redis is skipped; requests are rejected (or allowed, if FAIL_OPEN) instantly.
    HALF_OPEN -> after recovery_timeout, ONE probe request is sent to Redis.
                 Success closes the circuit, failure reopens it.

    Safe without locks: each worker runs one asyncio event loop and there is
    no await between the state checks and updates below.
    """

    def __init__(self, failure_threshold: int, recovery_timeout: float):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = "closed"
        self.failures = 0
        self.opened_at = 0.0
        self.probe_in_flight = False

    def allow(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.monotonic() - self.opened_at >= self.recovery_timeout:
                self.state = "half_open"
                self.probe_in_flight = True
                logger.warning("Circuit breaker HALF-OPEN: probing Redis")
                return True
            return False
        # half_open: only one probe at a time
        if not self.probe_in_flight:
            self.probe_in_flight = True
            return True
        return False

    def record_success(self) -> None:
        if self.state != "closed":
            logger.warning("Circuit breaker CLOSED: Redis recovered")
        self.state = "closed"
        self.failures = 0
        self.probe_in_flight = False

    def record_failure(self) -> None:
        self.probe_in_flight = False
        if self.state == "half_open":
            self._open()
            return
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        self.state = "open"
        self.opened_at = time.monotonic()
        logger.error(
            "Circuit breaker OPEN: skipping Redis for %.1fs", self.recovery_timeout
        )

    def retry_after(self) -> int:
        remaining = self.recovery_timeout - (time.monotonic() - self.opened_at)
        return max(1, math.ceil(remaining))


breaker = CircuitBreaker(
    failure_threshold=settings.CB_FAILURE_THRESHOLD,
    recovery_timeout=settings.CB_RECOVERY_TIMEOUT,
)

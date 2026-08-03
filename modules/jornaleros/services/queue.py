"""
queue.py — Rate Limiter y Cola Asíncrona para escrituras en Google Sheets.

Copia de modules/camiones/services/queue.py adaptada al módulo Jornaleros
(las filas se identifican por ID del jornalero, no por fila_id/auditoría).
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class QueueItem:
    """
    Elemento dentro de la cola de procesamiento.

    Atributos:
        jornalero_id: ID del registro en la BD local (col A del sheet).
        action:       Tipo de acción ("append" o "update_row").
        valores:      Lista de valores en orden de columnas (A-M).
        reintentos:   Contador de reintentos.
    """
    jornalero_id: str
    action: str
    valores: list
    reintentos: int = 0


class TokenBucketRateLimiter:
    """
    Token Bucket para no exceder el límite de API de Google Sheets
    (misma implementación que camiones).
    """

    def __init__(self, max_tokens: int, window_size: float):
        self.max_tokens = max_tokens
        self.window_size = window_size
        self.tokens = float(max_tokens)
        self._refill_rate = max_tokens / window_size
        self._last_refill = datetime.now(timezone.utc)
        self._lock = asyncio.Lock()

    async def acquire(self):
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
            await asyncio.sleep(0.1)

    def _refill(self):
        now = datetime.now(timezone.utc)
        elapsed = (now - self._last_refill).total_seconds()
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self._refill_rate)
        self._last_refill = now


class UpdateQueue:
    """
    Cola de actualizaciones con rate limiter y reintentos.
    """

    def __init__(
        self,
        write_callback,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        rate_limit_max: int = 10,
        rate_limit_window: float = 10.0,
    ):
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue()
        self._write_callback = write_callback
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._rate_limiter = TokenBucketRateLimiter(rate_limit_max, rate_limit_window)
        self._worker_task: asyncio.Task | None = None

    async def start(self):
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Cola de actualizaciones (jornaleros) iniciada.")

    async def stop(self):
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            logger.info("Cola de actualizaciones (jornaleros) detenida.")

    async def enqueue(self, item: QueueItem):
        await self._queue.put(item)
        logger.debug("Elemento encolado (jornalero %s, acción: %s).",
                     item.jornalero_id, item.action)

    def size(self) -> int:
        return self._queue.qsize()

    async def _worker_loop(self):
        while True:
            try:
                item = await self._queue.get()
                await self._process_item(item)
            except asyncio.CancelledError:
                logger.info("Worker de cola (jornaleros) cancelado.")
                break
            except Exception as e:
                logger.critical("Error crítico en el worker de la cola (jornaleros): %s", e, exc_info=True)

    async def _process_item(self, item: QueueItem):
        await self._rate_limiter.acquire()

        try:
            await self._write_callback(item)
            logger.info("Operación exitosa en Sheets: %s, jornalero %s",
                        item.action, item.jornalero_id)
        except Exception as e:
            if item.reintentos < self._max_retries:
                item.reintentos += 1
                delay = self._retry_base_delay * (2 ** (item.reintentos - 1))
                logger.warning(
                    "Error al sincronizar con Sheets (intento %s/%s): %s. Reintentando en %ss...",
                    item.reintentos, self._max_retries, e, delay
                )
                await asyncio.sleep(delay)
                await self._queue.put(item)
            else:
                logger.error(
                    "Sincronización fallida tras %s intentos: %s (jornalero %s)",
                    self._max_retries, e, item.jornalero_id
                )
                from modules.jornaleros.db.database import marcar_sincronizado
                await marcar_sincronizado(item.jornalero_id, error=str(e))
        finally:
            self._queue.task_done()

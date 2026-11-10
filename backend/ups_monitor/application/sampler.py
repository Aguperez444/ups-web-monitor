import asyncio
import logging

from ..domain.ports import SourceUnavailable
from .monitor import Monitor


logger = logging.getLogger(__name__)


async def sample_periodically(monitor: Monitor, stop: asyncio.Event, cleanup_seconds: float) -> None:
    clock = asyncio.get_running_loop().time
    next_cleanup = clock()
    while not stop.is_set():
        try:
            await asyncio.to_thread(monitor.capture)
        except SourceUnavailable as error:
            logger.warning("Muestra omitida: %s", error)
        except Exception:
            logger.exception("No se pudo almacenar la muestra del UPS")

        if clock() >= next_cleanup:
            try:
                await asyncio.to_thread(monitor.purge)
            except Exception:
                logger.exception("No se pudo aplicar la retención de métricas")
            else:
                next_cleanup = clock() + cleanup_seconds

        try:
            await asyncio.wait_for(stop.wait(), timeout=monitor.sample_interval_seconds)
        except asyncio.TimeoutError:
            continue

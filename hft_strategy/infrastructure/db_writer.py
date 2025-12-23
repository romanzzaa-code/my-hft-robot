# hft_strategy/db_writer.py
import asyncio
import asyncpg
import logging
from datetime import datetime, timezone
from typing import List, Tuple, Any
from hft_strategy.infrastructure.serializers import MarketDataSerializer

logger = logging.getLogger("DB_WRITER")

class TimescaleRepository:
    def __init__(self, db_config: dict):
        self.db_config = db_config
        self.pool = None

    async def connect(self):
        try:
            self.pool = await asyncpg.create_pool(**self.db_config)
            logger.info("✅ Repository connected to DB")
        except Exception as e:
            logger.error(f"DB Connection failed: {e}")
            raise

    async def save_ticks(self, records: List[Tuple]):
        if not self.pool or not records: return
        try:
            async with self.pool.acquire() as conn:
                await conn.copy_records_to_table('market_ticks', records=records, columns=['time', 'exch_time', 'symbol', 'price', 'volume', 'is_buyer_maker'])
        except Exception as e:
            logger.error(f"Trade write error: {e}")

    async def save_depth_snapshots(self, records: List[Tuple]):
        if not self.pool or not records: return
        try:
            async with self.pool.acquire() as conn:
                await conn.copy_records_to_table('market_depth_snapshots', records=records, columns=['time', 'exch_time', 'symbol', 'bids', 'asks', 'is_snapshot'])
        except Exception as e:
            logger.error(f"Depth write error: {e}")

    async def close(self):
        if self.pool:
            await self.pool.close()
            logger.info("DB Connection closed")

class BufferedTickWriter:
    def __init__(self, repository: TimescaleRepository, batch_size=1000, flush_interval=0.5):
        self.repo = repository
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.tick_buffer = []
        self.depth_buffer = []
        self._running = False
        self._flush_task = None

    async def start(self):
        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def add_event(self, event: Any):
        if not self._running: return
        event_type = getattr(event, 'type', 'unknown')
        
        local_dt = datetime.now(timezone.utc)
        # [FIX] Исправлено деление на 1000.0 (было 100.0)
        exch_dt = datetime.fromtimestamp(event.timestamp / 1000.0, tz=timezone.utc)

        if event_type == 'trade':
            self.tick_buffer.append((local_dt, exch_dt, event.symbol, event.price, event.volume, None))
        elif event_type == 'depth':
            bids_json, asks_json = MarketDataSerializer.serialize_depth(event.bids, event.asks)
            self.depth_buffer.append((local_dt, exch_dt, event.symbol, bids_json, asks_json, event.is_snapshot))

        if len(self.tick_buffer) >= self.batch_size: await self._flush_ticks()
        if len(self.depth_buffer) >= 10: await self._flush_depth()

    async def _flush(self):
        await self._flush_ticks()
        await self._flush_depth()

    async def _flush_ticks(self):
        if self.tick_buffer:
            await self.repo.save_ticks(self.tick_buffer[:])
            self.tick_buffer.clear()

    async def _flush_depth(self):
        if self.depth_buffer:
            await self.repo.save_depth_snapshots(self.depth_buffer[:])
            self.depth_buffer.clear()

    async def _periodic_flush(self):
        while self._running:
            await asyncio.sleep(self.flush_interval)
            await self._flush()

    async def stop(self):
        self._running = False
        if self._flush_task: self._flush_task.cancel()
        await self._flush()

class NullRepository:
    """
    Пустая реализация репозитория.
    Соблюдает интерфейс TimescaleRepository, но методы ничего не делают.
    """
    async def connect(self):
        logging.getLogger("DB_WRITER").info("⚠️ NullRepository: DB connection skipped (Mode: NO_DB)")

    async def save_ticks(self, records):
        pass

    async def save_depth_snapshots(self, records):
        pass

    async def close(self):
        pass

class NullTickWriter:
    """
    Пустая реализация писателя.
    Принимает события, но никуда их не сохраняет и не буферизирует.
    """
    def __init__(self, repository=None, batch_size=1000):
        # repository здесь даже не нужен, но оставляем для совместимости сигнатур
        pass

    async def start(self):
        logging.getLogger("DB_WRITER").info("⚠️ NullTickWriter started: History will NOT be saved.")

    async def add_event(self, event):
        # Просто игнорируем событие
        pass

    async def stop(self):
        pass        
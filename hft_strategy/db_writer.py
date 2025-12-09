# hft_strategy/db_writer.py
import asyncio
import asyncpg
import logging
from datetime import datetime, timezone
from typing import List, Tuple

logger = logging.getLogger("DB_WRITER")

# --- Слой Инфраструктуры (Repository) ---
class TimescaleRepository:
    """
    Отвечает ТОЛЬКО за отправку данных в Postgres/TimescaleDB.
    Принцип Single Responsibility (SRP).
    """
    def __init__(self, db_config):
        self.db_config = db_config
        self.pool = None

    async def connect(self):
        try:
            self.pool = await asyncpg.create_pool(**self.db_config)
            logger.info("✅ Repository connected to DB")
        except Exception as e:
            logger.error(f"DB Connection failed: {e}")
            raise

    async def save_batch(self, records: List[Tuple]):
        if not self.pool:
            return
        
        try:
            async with self.pool.acquire() as conn:
                # FIX: Добавлен столбец 'exch_time' в список
                await conn.copy_records_to_table(
                    'market_ticks',
                    records=records,
                    columns=['time', 'exch_time', 'symbol', 'price', 'volume', 'is_buyer_maker']
                )
            logger.debug(f"💾 Repository saved {len(records)} ticks")
        except Exception as e:
            logger.error(f"Repository write error: {e}")

    async def close(self):
        if self.pool:
            await self.pool.close()
            logger.info("DB Connection closed")

# --- Слой Приложения (Service/Buffer) ---
class BufferedTickWriter:
    def __init__(self, repository: TimescaleRepository, batch_size=1000, flush_interval=0.5):
        self.repo = repository
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        
        self.buffer = []
        self._running = False
        self._flush_task = None

    async def start(self):
        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def add_tick(self, tick):
        if not self._running:
            return

        # Архитектурное улучшение: Разделяем время поступления и время биржи
        # 'time' (PK) -> Local Time (сейчас) - важно для строгого порядка в TimescaleDB
        local_dt = datetime.now(timezone.utc)
        
        # 'exch_time' -> Exchange Time (из тика)
        exch_dt = datetime.fromtimestamp(tick.timestamp / 1000.0, tz=timezone.utc)

        # Формируем кортеж согласно порядку columns в save_batch
        record = (
            local_dt,      # time
            exch_dt,       # exch_time (FIX: теперь не null)
            tick.symbol,   # symbol
            tick.price,    # price
            tick.volume,   # volume
            None           # is_buyer_maker (пока null, если парсер не отдает)
        )
        
        self.buffer.append(record)

        if len(self.buffer) >= self.batch_size:
            await self._flush()

    async def _flush(self):
        if not self.buffer:
            return

        records_to_save = self.buffer[:]
        self.buffer.clear()
        
        await self.repo.save_batch(records_to_save)

    async def _periodic_flush(self):
        while self._running:
            await asyncio.sleep(self.flush_interval)
            await self._flush()

    async def stop(self):
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
        await self._flush()
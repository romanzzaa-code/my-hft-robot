# hft_strategy/db_writer.py
import asyncio
import asyncpg
import logging
# import json <-- Убрали медленный json
from datetime import datetime, timezone
from typing import List, Tuple, Any

# Импортируем наш быстрый сериализатор (SRP)
from hft_strategy.infrastructure.serializers import MarketDataSerializer

logger = logging.getLogger("DB_WRITER")

class TimescaleRepository:
    def __init__(self, db_config: dict):
        self.db_config = db_config
        self.pool = None

    async def connect(self):
        try:
            # db_config приходит уже как словарь из main.py
            self.pool = await asyncpg.create_pool(**self.db_config)
            logger.info("✅ Repository connected to DB")
        except Exception as e:
            logger.error(f"DB Connection failed: {e}")
            raise

    async def save_ticks(self, records: List[Tuple]):
        if not self.pool or not records:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.copy_records_to_table(
                    'market_ticks',
                    records=records,
                    columns=['time', 'exch_time', 'symbol', 'price', 'volume', 'is_buyer_maker']
                )
            logger.debug(f"💾 Saved {len(records)} ticks")
        except Exception as e:
            logger.error(f"Trade write error: {e}")

    async def save_depth_snapshots(self, records: List[Tuple]):
        if not self.pool or not records:
            return
        try:
            async with self.pool.acquire() as conn:
                # asyncpg корректно пишет JSON-строки в JSONB колонки
                await conn.copy_records_to_table(
                    'market_depth_snapshots',
                    records=records,
                    columns=['time', 'exch_time', 'symbol', 'bids', 'asks', 'is_snapshot']
                )
            logger.debug(f"💾 Saved {len(records)} snapshots")
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
        if not self._running:
            return

        event_type = getattr(event, 'type', 'unknown')
        
        # Оптимизация: берем время один раз
        local_dt = datetime.now(timezone.utc)
        exch_dt = datetime.fromtimestamp(event.timestamp / 100.0, tz=timezone.utc)

        # 1. ТИКИ
        if event_type == 'trade':
            record = (
                local_dt,
                exch_dt,
                event.symbol,
                event.price,
                event.volume,
                None 
            )
            self.tick_buffer.append(record)

        # 2. СТАКАНЫ (КРИТИЧЕСКАЯ СЕКЦИЯ ПО СКОРОСТИ)
        elif event_type == 'depth':
            # Делегируем сериализацию отдельному классу (он юзает orjson)
            bids_json, asks_json = MarketDataSerializer.serialize_depth(event.bids, event.asks)
            
            record = (
                local_dt,
                exch_dt,
                event.symbol,
                bids_json, # Быстрая строка JSON
                asks_json, 
                event.is_snapshot
            )
            self.depth_buffer.append(record)

        # Логика сброса буферов
        if len(self.tick_buffer) >= self.batch_size:
            await self._flush_ticks()
        
        # Стаканы "тяжелее", сбрасываем чаще
        if len(self.depth_buffer) >= 10: 
            await self._flush_depth()

    async def _flush(self):
        await self._flush_ticks()
        await self._flush_depth()

    async def _flush_ticks(self):
        if self.tick_buffer:
            # Быстрое копирование списка и очистка
            ticks_to_save = self.tick_buffer[:]
            self.tick_buffer.clear()
            await self.repo.save_ticks(ticks_to_save)

    async def _flush_depth(self):
        if self.depth_buffer:
            depth_to_save = self.depth_buffer[:]
            self.depth_buffer.clear()
            await self.repo.save_depth_snapshots(depth_to_save)

    async def _periodic_flush(self):
        while self._running:
            await asyncio.sleep(self.flush_interval)
            await self._flush()

    async def stop(self):
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
        # Финальный сброс остатков
        await self._flush()
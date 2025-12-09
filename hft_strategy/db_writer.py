import asyncio
import asyncpg
import logging
from datetime import datetime, timezone

logger = logging.getLogger("DB_WRITER")

class AsyncDBWriter:
    def __init__(self, db_config, batch_size=1000, flush_interval=0.5):
        self.db_config = db_config
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        
        self.pool = None
        self.buffer = []
        self._running = False
        self._flush_task = None

    async def connect(self):
        """Создание пула соединений"""
        try:
            self.pool = await asyncpg.create_pool(**self.db_config)
            logger.info("✅ DB Connection pool created")
            self._running = True
            # Запускаем фоновую задачу для сброса по таймеру
            self._flush_task = asyncio.create_task(self._periodic_flush())
        except Exception as e:
            logger.error(f"Failed to connect to DB: {e}")
            raise

    async def add_tick(self, tick):
        """Добавление тика в буфер"""
        if not self._running:
            return

        # Конвертируем Timestamp (ms) в Datetime для Postgres
        dt = datetime.fromtimestamp(tick.timestamp / 1000.0, tz=timezone.utc)
        
        # Формируем кортеж (time, symbol, price, volume, is_buyer_maker)
        # is_buyer_maker пока ставим None, так как в TickData этого нет (можно добавить позже)
        record = (dt, tick.symbol, tick.price, tick.volume, None)
        
        self.buffer.append(record)

        # Если буфер переполнен — сбрасываем немедленно
        if len(self.buffer) >= self.batch_size:
            await self._flush()

    async def _flush(self):
        """Отправка данных в базу"""
        if not self.buffer or not self.pool:
            return

        # Забираем данные из буфера и очищаем его
        records_to_save = self.buffer[:]
        self.buffer.clear()

        try:
            async with self.pool.acquire() as conn:
                # Магия скорости: COPY вместо INSERT
                await conn.copy_records_to_table(
                    'market_ticks',
                    records=records_to_save,
                    columns=['time', 'symbol', 'price', 'volume', 'is_buyer_maker']
                )
            logger.debug(f"💾 Saved {len(records_to_save)} ticks")
        except Exception as e:
            logger.error(f"Failed to flush data: {e}")
            # Можно вернуть данные обратно в буфер, но для HFT иногда лучше потерять, чем остановить мир

    async def _periodic_flush(self):
        """Фоновая задача: сбрасывает буфер каждые N секунд"""
        while self._running:
            await asyncio.sleep(self.flush_interval)
            await self._flush()

    async def stop(self):
        """Корректное завершение"""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
        
        # Финальный сброс остатков
        await self._flush()
        
        if self.pool:
            await self.pool.close()
            logger.info("DB Connection closed")
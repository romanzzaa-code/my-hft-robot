import asyncio
import logging
import sys
import os

# --- ХАК ДЛЯ ПУТЕЙ ---
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
possible_paths = [
    os.path.join(project_root, "hft_core", "build", "Release"),
    os.path.join(project_root, "build", "Release"),
]
for p in possible_paths:
    if os.path.exists(p):
        sys.path.insert(0, p)
        break

from market_bridge import MarketBridge
from db_writer import AsyncDBWriter  # <-- ИМПОРТ

# Конфиг базы
DB_CONFIG = {
    "user": "hft_user",
    "password": "password",
    "database": "hft_data",
    "host": "localhost",
    "port": "5432"
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Main")

async def main():
    loop = asyncio.get_running_loop()
    
    # 1. Инициализируем Писателя
    db_writer = AsyncDBWriter(DB_CONFIG)
    await db_writer.connect()
    
    # 2. Инициализируем Мост
    bridge = MarketBridge("BTCUSDT", loop)
    await bridge.start()
    
    logger.info("🚀 System running. Saving ticks to DB...")
    
    try:
        while True:
            # 3. Читаем тики и отправляем в БД
            tick = await bridge.get_tick()
            
            # Отправляем в писатель (это не блокирует цикл, просто добавляет в буфер)
            await db_writer.add_tick(tick)
            
            # Для отладки выводим каждый 100-й тик
            if tick.timestamp % 100 == 0:
                 print(f"Tick: {tick.price} -> Buffer: {len(db_writer.buffer)}")
            
    except KeyboardInterrupt:
        logger.warning("Shutdown signal received")
    finally:
        await bridge.stop()
        await db_writer.stop() # <-- Важно сохранить остатки буфера!
        logger.info("Shutdown complete")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
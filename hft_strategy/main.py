# hft_strategy/main.py
import asyncio
import logging
import sys
import os

# --- ХАК ДЛЯ ПУТЕЙ (Оставляем, это необходимо для C++ модуля) ---
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
possible_paths = [
    os.path.join(project_root, "hft_core", "build", "Release"),
    os.path.join(project_root, "build", "Release"),
]
for p in possible_paths:
    if os.path.exists(p):
        sys.path.insert(0, p)
        break

# Теперь импортируем C++ модуль ЗДЕСЬ, чтобы создать зависимости
import hft_core 

from market_bridge import MarketBridge
from db_writer import TimescaleRepository, BufferedTickWriter # Новые классы

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
    
    # 1. СБОРКА ИНФРАСТРУКТУРЫ (Database)
    logger.info("🔧 Initializing Database Layer...")
    repo = TimescaleRepository(DB_CONFIG)
    await repo.connect()
    
    # Внедряем репозиторий в буфер
    db_writer = BufferedTickWriter(repository=repo, batch_size=1000)
    await db_writer.start()
    
    # 2. СБОРКА ЯДРА (C++ Core)
    logger.info("🔧 Initializing C++ Core...")
    # Создаем стратегию парсинга (можно легко заменить на BinanceParser)
    parser = hft_core.BybitParser() 
    
    # Внедряем парсер в стример
    streamer = hft_core.ExchangeStreamer(parser)
    
    # 3. СБОРКА МОСТА (Application Layer)
    # Внедряем стример в мост
    bridge = MarketBridge("BTCUSDT", streamer, loop)
    
    # Запуск
    await bridge.start()
    
    logger.info("🚀 System is RUNNING. (Ctrl+C to stop)")
    
    try:
        while True:
            # Читаем тики из моста
            tick = await bridge.get_tick()
            
            # Пишем в буфер (он сам решит, когда сбросить в БД)
            await db_writer.add_tick(tick)
            
            if tick.timestamp % 100 == 0:
                 print(f"Tick: {tick.price} -> Buffered: {len(db_writer.buffer)}")
            
    except KeyboardInterrupt:
        logger.warning("Shutdown signal received")
    finally:
        # Корректное завершение в обратном порядке
        await bridge.stop()
        await db_writer.stop()
        await repo.close()
        logger.info("Shutdown complete")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
# hft_strategy/main.py
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

import hft_core 
from market_bridge import MarketBridge
from db_writer import TimescaleRepository, BufferedTickWriter

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
    if sys.platform == 'win32':
        # Фикс для Windows (asyncio + SelectorEventLoop)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    loop = asyncio.get_running_loop()
    
    # 1. БД
    logger.info("🔧 Initializing Database Layer...")
    repo = TimescaleRepository(DB_CONFIG)
    await repo.connect()
    
    # Batch size поменьше для теста
    db_writer = BufferedTickWriter(repository=repo, batch_size=100)
    await db_writer.start()
    
    # 2. C++ Core
    logger.info("🔧 Initializing C++ Core...")
    parser = hft_core.BybitParser() 
    streamer = hft_core.ExchangeStreamer(parser)
    
    # 3. Мост
    # Bridge сам подпишется на orderbook.50 и publicTrade
    bridge = MarketBridge("BTCUSDT", streamer, loop)
    
    await bridge.start()
    
    logger.info("🚀 System is RUNNING. Collecting Trades AND OrderBooks...")
    
    try:
        while True:
            # Получаем любое событие (тик или стакан)
            event = await bridge.get_tick()
            
            # Отправляем в буфер писателя
            await db_writer.add_event(event)
            
            # Логгирование для отладки
            # Если это стакан, покажем лучший бид/аск
            if getattr(event, 'type', '') == 'depth':
                # event.bids - это список объектов PriceLevel
                best_bid = event.bids[0].price if event.bids else 0
                best_ask = event.asks[0].price if event.asks else 0
                print(f"📚 BOOK | Bid: {best_bid} | Ask: {best_ask} | TS: {event.timestamp}")
            elif getattr(event, 'type', '') == 'trade':
                pass # Слишком часто, не спамим

    except KeyboardInterrupt:
        logger.warning("Shutdown signal received")
    finally:
        await bridge.stop()
        await db_writer.stop()
        await repo.close()
        logger.info("Shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
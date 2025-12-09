# hft_strategy/main.py
import asyncio
import logging
import sys
import os

# --- ХАК ДЛЯ ПУТЕЙ (оставляем пока не упакуем в пакет) ---
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
from config import DB_CONFIG, TRADING_CONFIG # <-- Импортируем конфиги

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Main")

async def main():
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    loop = asyncio.get_running_loop()
    
    # 1. БД (Inject Config)
    logger.info("🔧 Initializing Database Layer...")
    # Превращаем dataclass в dict
    repo = TimescaleRepository(DB_CONFIG.as_dict())
    await repo.connect()
    
    db_writer = BufferedTickWriter(repository=repo, batch_size=100)
    await db_writer.start()
    
    # 2. C++ Core
    logger.info("🔧 Initializing C++ Core...")
    parser = hft_core.BybitParser() 
    streamer = hft_core.ExchangeStreamer(parser)
    
    # 3. Мост (Inject Symbol & URL)
    # Теперь мы можем легко поменять Mainnet на Testnet в config.py
    bridge = MarketBridge(
        target_symbol=TRADING_CONFIG.symbol, 
        ws_url=TRADING_CONFIG.ws_url, 
        streamer=streamer, 
        loop=loop
    )
    
    await bridge.start()
    
    logger.info(f"🚀 System RUNNING. Symbol: {TRADING_CONFIG.symbol}")
    
    try:
        while True:
            event = await bridge.get_tick()
            await db_writer.add_event(event)
            
            # Оставим минимальный лог для healthcheck
            if getattr(event, 'type', '') == 'depth':
                 # event.bids - это список объектов PriceLevel
                best_bid = event.bids[0].price if event.bids else 0
                best_ask = event.asks[0].price if event.asks else 0
                # Чтобы не спамить, можно выводить раз в N секунд, но пока так
                # print(f"📚 {TRADING_CONFIG.symbol} | Bid: {best_bid} | Ask: {best_ask}") 
                pass

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
# hft_strategy/live_bot.py
import asyncio
import logging
import sys
import os
from typing import Dict
from dotenv import load_dotenv

load_dotenv()

# --- PATH HACK ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

build_path_release = os.path.join(project_root, "hft_core", "build", "Release")
if os.path.exists(build_path_release):
    if build_path_release not in sys.path:
        sys.path.insert(0, build_path_release)
        print(f"🔌 Loaded C++ Core from: {build_path_release}")
else:
    print(f"⚠️ WARNING: Build path not found: {build_path_release}")
# -----------------

import hft_core 
# [UPDATED] Импортируем TARGET_COINS
from hft_strategy.config import TRADING_CONFIG, DB_CONFIG, TARGET_COINS
from hft_strategy.infrastructure.market_bridge import MarketBridge
from hft_strategy.infrastructure.execution import BybitExecutionHandler
from hft_strategy.domain.strategy_config import get_config
from hft_strategy.strategies.adaptive_live_strategy import AdaptiveWallStrategy
from hft_strategy.infrastructure.db_writer import TimescaleRepository, BufferedTickWriter

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("MAIN")

async def main():
    # 1. Используем список монет из конфига
    symbols = TARGET_COINS
    logger.info(f"🤖 STARTING MULTI-BOT for: {symbols}")
    
    # 2. Init Database Writer
    logger.info("💾 Connecting to Database...")
    repo = TimescaleRepository(DB_CONFIG.as_dict())
    await repo.connect()
    
    # Общий буфер для всех монет
    db_writer = BufferedTickWriter(repository=repo, batch_size=1000, flush_interval=0.5)
    await db_writer.start()

    # 3. Init Executor (Один на всех)
    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    executor = BybitExecutionHandler(api_key, api_secret, sandbox=False)

    # 4. Init Strategies (Карта: Symbol -> Strategy)
    strategies: Dict[str, AdaptiveWallStrategy] = {}
    
    logger.info("🔧 Initializing strategies for each symbol...")
    for sym in symbols:
        try:
            # Получаем спецификации инструмента
            tick_size, lot_size, min_qty = await executor.fetch_instrument_info(sym)
            
            # Создаем конфиг для конкретной монеты
            cfg = get_config(sym)
            cfg.tick_size = tick_size
            cfg.lot_size = lot_size
            cfg.min_qty = min_qty
            
            # Создаем экземпляр стратегии
            strategies[sym] = AdaptiveWallStrategy(executor, cfg)
            logger.info(f"✅ Armed {sym}: Tick={tick_size}, Lot={lot_size}")
            
        except Exception as e:
            logger.error(f"❌ Failed to init strategy for {sym}: {e}")
            # Не падаем, если одна монета сбойнула, продолжаем с остальными
            continue
            
    if not strategies:
        logger.critical("❌ No strategies initialized! Exiting.")
        return

    # 5. Init Core & Bridge
    parser = hft_core.BybitParser()
    streamer = hft_core.ExchangeStreamer(parser)
    loop = asyncio.get_running_loop()
    bridge = MarketBridge(TRADING_CONFIG.ws_url, streamer, loop)
    
    # 6. Start & Subscribe
    await bridge.start()
    logger.info(f"📡 Subscribing to market data for {len(strategies)} symbols...")
    
    # Подписываемся сразу на весь список успешных монет
    active_symbols = list(strategies.keys())
    await bridge.sync_heavy_subscriptions(active_symbols)

    logger.info("🟢 LIVE SYSTEM ACTIVE. Multi-Asset Mode.")

    try:
        while True:
            event = await bridge.get_tick()
            
            # Пишем в базу всё подряд
            await db_writer.add_event(event)

            # Маршрутизация событий (Dispatcher)
            # Если событие пришло по монете, для которой есть стратегия -> передаем
            target_strategy = strategies.get(event.symbol)
            
            if target_strategy:
                evt_type = getattr(event, 'type', '')
                if evt_type == 'depth':
                    await target_strategy.on_depth(event)
            # else: 
                # Тики по неизвестным монетам просто игнорируем (или пишем в лог, если нужно)
                
    except KeyboardInterrupt:
        logger.info("🛑 Stopping by user request...")
    except Exception as e:
        logger.critical(f"💥 CRITICAL ERROR: {e}", exc_info=True)
    finally:
        logger.info("💤 Shutting down services...")
        await bridge.stop()
        await db_writer.stop()
        await repo.close()
        logger.info("👋 Bot stopped.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
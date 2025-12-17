# hft_strategy/live_bot.py
import asyncio
import logging
import sys
import os
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
from hft_strategy.config import TRADING_CONFIG, DB_CONFIG # [NEW] Added DB_CONFIG
from hft_strategy.infrastructure.market_bridge import MarketBridge
from hft_strategy.infrastructure.execution import BybitExecutionHandler
from hft_strategy.domain.strategy_config import get_config
from hft_strategy.strategies.adaptive_live_strategy import AdaptiveWallStrategy

# [NEW] Импортируем писателя в БД
from hft_strategy.infrastructure.db_writer import TimescaleRepository, BufferedTickWriter

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("MAIN")

async def main():
    symbol = TRADING_CONFIG.symbol
    logger.info(f"🤖 STARTING LIVE BOT for {symbol}")
    
    cfg = get_config(symbol)
    
    # 1. Init Database Writer [NEW]
    logger.info("💾 Connecting to Database...")
    repo = TimescaleRepository(DB_CONFIG.as_dict())
    await repo.connect()
    
    # Буфер будет сбрасывать данные в БД каждые 1000 тиков или раз в 0.5 сек
    db_writer = BufferedTickWriter(repository=repo, batch_size=1000, flush_interval=0.5)
    await db_writer.start()

    # 2. Init Strategy Components
    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    executor = BybitExecutionHandler(api_key, api_secret, sandbox=False)
    logger.info("📏 Fetching instrument specifications...")
    tick_size, lot_size, min_qty = await executor.fetch_instrument_info(symbol)
    
    # Обновляем конфиг реальными данными
    cfg.tick_size = tick_size
    cfg.lot_size = lot_size
    cfg.min_qty = min_qty
    
    logger.info(f"✅ Config Updated: Tick={cfg.tick_size}, Lot={cfg.lot_size}, Order=${cfg.order_amount_usdt}")
    strategy = AdaptiveWallStrategy(executor, cfg)
    

    # 3. Init Core & Bridge
    parser = hft_core.BybitParser()
    streamer = hft_core.ExchangeStreamer(parser)
    loop = asyncio.get_running_loop()
    bridge = MarketBridge(TRADING_CONFIG.ws_url, streamer, loop)
    
    # 4. Start
    await bridge.start()
    logger.info("📡 Subscribing to market data...")
    await bridge.sync_heavy_subscriptions([symbol])

    logger.info("🟢 LIVE SYSTEM ACTIVE. Trading & Recording...")

    try:
        while True:
            event = await bridge.get_tick()
            
            # [NEW] Пишем событие в базу (асинхронно, в буфер)
            # Это очень быстрая операция, она не затормозит стратегию
            await db_writer.add_event(event)

            # Передаем в стратегию
            evt_type = getattr(event, 'type', '')
            if evt_type == 'depth':
                await strategy.on_depth(event)
                
    except KeyboardInterrupt:
        logger.info("🛑 Stopping by user request...")
    except Exception as e:
        logger.critical(f"💥 CRITICAL ERROR: {e}", exc_info=True)
    finally:
        # Graceful Shutdown [NEW]
        logger.info("💤 Shutting down services...")
        await bridge.stop()
        await db_writer.stop() # Сброс остатков буфера на диск
        await repo.close()
        logger.info("👋 Bot stopped.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
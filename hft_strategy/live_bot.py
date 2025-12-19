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
else:
    print(f"⚠️ WARNING: Build path not found: {build_path_release}")
# -----------------

import hft_core 
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
    symbols = TARGET_COINS
    logger.info(f"🤖 STARTING HFT ENGINE | Assets: {len(symbols)}")
    
    # 1. DB & Execution
    logger.info("💾 Connecting to Database...")
    repo = TimescaleRepository(DB_CONFIG.as_dict())
    await repo.connect()
    db_writer = BufferedTickWriter(repository=repo, batch_size=1000)
    await db_writer.start()

    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    if not api_key:
        logger.warning("⚠️ Running in ANONYMOUS mode (Public Data Only)")

    executor = BybitExecutionHandler(api_key, api_secret, sandbox=False)

    # 2. Init Strategies
    strategies: Dict[str, AdaptiveWallStrategy] = {}
    logger.info("🔧 Arming strategies...")
    
    for sym in symbols:
        try:
            tick_size, lot_size, min_qty = await executor.fetch_instrument_info(sym)
            cfg = get_config(sym)
            cfg.tick_size = tick_size
            cfg.lot_size = lot_size
            cfg.min_qty = min_qty
            
            strategies[sym] = AdaptiveWallStrategy(executor, cfg)
            logger.info(f"   ✅ {sym} READY")
        except Exception as e:
            logger.error(f"   ❌ {sym} Failed: {e}")

    if not strategies:
        return

    # 3. CORE: Shared Queue & Dual Streamers
    # Создаем одну очередь на всех
    shared_queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    # --- PUBLIC STREAM (Market Data) ---
    pub_parser = hft_core.BybitParser()
    pub_streamer = hft_core.ExchangeStreamer(pub_parser)
    public_bridge = MarketBridge(TRADING_CONFIG.ws_url, pub_streamer, loop, queue=shared_queue)

    # --- PRIVATE STREAM (Executions) ---
    priv_bridge = None
    if api_key:
        priv_parser = hft_core.BybitParser()
        priv_streamer = hft_core.ExchangeStreamer(priv_parser)
        # Используем URL из конфига (wss://stream.bybit.com/v5/private)
        priv_bridge = MarketBridge(TRADING_CONFIG.private_ws_url, priv_streamer, loop, queue=shared_queue)

    # 4. Start Engines
    await public_bridge.start()
    
    # Подписка на публичные данные
    await public_bridge.sync_heavy_subscriptions(list(strategies.keys()))

    if priv_bridge:
        await priv_bridge.start()
        # Аутентификация и подписка на исполнения
        priv_bridge.authenticate(api_key, api_secret)
        priv_bridge.subscribe_executions()

    logger.info("🚀 SYSTEM LIVE. Waiting for events...")

    try:
        while True:
            # Читаем из общей очереди. Тут будут и Trades, и Depth, и Executions
            event = await shared_queue.get()
            
            # 1. Логирование в БД (кроме приватных событий, если не нужно)
            evt_type = getattr(event, 'type', 'unknown')
            if evt_type in ['trade', 'depth']:
                await db_writer.add_event(event)

            # 2. Маршрутизация
            target_strat = strategies.get(event.symbol)
            if target_strat:
                if evt_type == 'depth':
                    await target_strat.on_depth(event)
                
                # 🔥 ГЛАВНОЕ ИЗМЕНЕНИЕ 🔥
                elif evt_type == 'execution':
                    # Передаем управление стратегии мгновенно
                    await target_strat.on_execution(event)

    except KeyboardInterrupt:
        logger.info("🛑 Stopping...")
    except Exception as e:
        logger.critical(f"💥 CRASH: {e}", exc_info=True)
    finally:
        await public_bridge.stop()
        if priv_bridge:
            await priv_bridge.stop()
        await db_writer.stop()
        await repo.close()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
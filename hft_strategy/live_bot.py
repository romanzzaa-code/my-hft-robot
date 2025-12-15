# hft_strategy/live_bot.py
import asyncio
import logging
import sys
import os
from dotenv import load_dotenv

load_dotenv()

# --- PATH HACK (ПРИНУДИТЕЛЬНЫЙ) ---
# 1. Определяем, где мы находимся
current_dir = os.path.dirname(os.path.abspath(__file__)) # .../hft_strategy
project_root = os.path.dirname(current_dir)              # .../ant (Корень проекта)

# 2. Добавляем корень проекта в sys.path (чтобы работали импорты hft_strategy.xxx)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 3. Добавляем путь к скомпилированному C++ ядру
build_path_release = os.path.join(project_root, "hft_core", "build", "Release")
if os.path.exists(build_path_release):
    if build_path_release not in sys.path:
        sys.path.insert(0, build_path_release)
        print(f"🔌 Loaded C++ Core from: {build_path_release}")
else:
    print(f"⚠️ WARNING: Build path not found: {build_path_release}")
# ----------------------------------

# Теперь импорты заработают
import hft_core 
from hft_strategy.config import TRADING_CONFIG
from hft_strategy.infrastructure.market_bridge import MarketBridge
from hft_strategy.infrastructure.execution import BybitExecutionHandler
from hft_strategy.strategies.live_strategy import WallBounceLive
from hft_strategy.domain.strategy_config import get_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("MAIN")

async def main():
    symbol = "SOLUSDT"
    logger.info(f"🤖 STARTING LIVE BOT for {symbol}")
    
    # 1. Config
    cfg = get_config(symbol)
    logger.info(f"🔧 Strategy Config: Wall={cfg.wall_vol_threshold}")

    # 2. Execution (Read-Only Mode)
    # Ключи берем из ENV или оставляем пустыми для Read-Only
    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    
    executor = BybitExecutionHandler(api_key, api_secret, sandbox=False)
    
    # 3. Strategy
    strategy = WallBounceLive(executor, cfg)

    # 4. C++ Core
    parser = hft_core.BybitParser()
    streamer = hft_core.ExchangeStreamer(parser)
    
    # 5. Bridge
    loop = asyncio.get_running_loop()
    bridge = MarketBridge(TRADING_CONFIG.ws_url, streamer, loop)
    
    # 6. Start
    await bridge.start()
    
    # Подписка
    logger.info("📡 Subscribing to market data...")
    await bridge.subscribe_to_tickers([symbol]) 
    await bridge.sync_heavy_subscriptions([symbol])

    logger.info("🟢 LIVE SYSTEM ACTIVE. Waiting for Walls...")

    try:
        while True:
            # Читаем события из очереди
            event = await bridge.get_tick()
            
            # Маршрутизация событий
            evt_type = getattr(event, 'type', '')
            
            if evt_type == 'depth':
                await strategy.on_depth(event)
            # Можно добавить обработку тикеров или сделок, если нужно
                
    except KeyboardInterrupt:
        logger.info("🛑 Stopping...")
    finally:
        await bridge.stop()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
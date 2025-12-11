# hft_strategy/main.py
import asyncio
import logging
import sys
import os

# --- PATH HACKS (Чтобы Python видел нашу C++ библиотеку) ---
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
from config import DB_CONFIG, TRADING_CONFIG
from market_bridge import MarketBridge
from db_writer import TimescaleRepository, BufferedTickWriter

# Импортируем наши новые сервисы
from services.instrument_provider import BybitInstrumentProvider
from services.market_scanner import MarketScanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Main")

# --- ФОНОВЫЕ ЗАДАЧИ (BACKGROUND TASKS) ---

async def daily_discovery_loop(provider: BybitInstrumentProvider, bridge: MarketBridge):
    """
    ЭТАП 1: Ежедневная разведка.
    Ищет новые монеты для копитрейдинга и подписывает сканер на их тикеры.
    """
    while True:
        try:
            logger.info("🌍 Starting Daily Discovery...")
            # 1. Запрос к API Bybit
            all_symbols = await provider.get_active_copytrading_symbols()
            
            if all_symbols:
                logger.info(f"✅ Discovery found {len(all_symbols)} pairs. Subscribing to TICKERS...")
                # 2. Подписка на легкий поток
                await bridge.subscribe_to_tickers(all_symbols)
            else:
                logger.warning("⚠️ Discovery returned empty list!")
                
        except Exception as e:
            logger.error(f"❌ Discovery Error: {e}")
        
        # Спим 24 часа (86400 секунд)
        await asyncio.sleep(86400)

async def hot_rotation_loop(scanner: MarketScanner, bridge: MarketBridge):
    """
    ЭТАП 2: Минутная ротация.
    Проверяет, кто сейчас в топе, и обновляет тяжелые подписки (стаканы).
    """
    # Даем системе 15 секунд на "разогрев" (получение первых тикеров), прежде чем выбирать топ
    await asyncio.sleep(15)
    
    while True:
        try:
            # 1. Спрашиваем у сканера топ монет
            top_coins = scanner.get_top_coins()
            
            if top_coins:
                # 2. Синхронизируем подписки (Bridge сам отпишется от старых и подпишется на новые)
                await bridge.sync_heavy_subscriptions(top_coins)
                
                logger.info(f"🔥 ACTIVE HOT TOP-5: {top_coins}")
            else:
                logger.info("❄️ Scanner is still warming up...")

        except Exception as e:
            logger.error(f"❌ Rotation Error: {e}")
            
        # Проверяем топ раз в минуту
        await asyncio.sleep(60)

# --- ГЛАВНАЯ ФУНКЦИЯ ---

async def main():
    # Фикс для Windows
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    loop = asyncio.get_running_loop()

    # 1. Инициализация Базы Данных
    logger.info("🔧 Initializing Database...")
    repo = TimescaleRepository(DB_CONFIG.as_dict())
    await repo.connect()
    
    # Batch size = 2000, так как поток от 5 монет будет плотным
    db_writer = BufferedTickWriter(repository=repo, batch_size=2000)
    await db_writer.start()

    # 2. Инициализация C++ Core
    logger.info("🔧 Initializing C++ Core...")
    parser = hft_core.BybitParser() 
    streamer = hft_core.ExchangeStreamer(parser)

    # 3. Инициализация Сервисов
    provider = BybitInstrumentProvider() # Разведчик
    scanner = MarketScanner(top_size=5)  # Аналитик (хранит топ-5)

    # 4. Инициализация Моста
    bridge = MarketBridge(
        ws_url=TRADING_CONFIG.ws_url, 
        streamer=streamer, 
        loop=loop
    )
    
    # 5. [WIRING] СВЯЗЫВАНИЕ C++ И PYTHON
    # Самый важный момент!
    # Когда C++ получает TickerData, он вызывает scanner.on_ticker_update напрямую.
    # Тикеры НЕ попадают в общую очередь (get_tick), чтобы не засорять её.
    streamer.set_ticker_callback(lambda t: scanner.on_ticker_update(t)) 
    
    # Запускаем WebSocket
    await bridge.start()

    # 6. Запускаем фоновые процессы "Воронки"
    # Discovery -> найдет монеты -> Bridge подпишется на тикеры
    asyncio.create_task(daily_discovery_loop(provider, bridge))
    # Rotation -> возьмет топ из Scanner -> Bridge подпишется на стаканы
    asyncio.create_task(hot_rotation_loop(scanner, bridge))

    logger.info("🚀 SYSTEM STARTED. Funnel Architecture is ACTIVE.")

    # 7. Главный цикл (Обработка Сделок и Стаканов)
    try:
        while True:
            # Читаем из очереди только "Тяжелые" данные (Trade/Depth),
            # которые нужны для стратегии и записи в БД.
            event = await bridge.get_tick()
            
            # Пишем в базу
            await db_writer.add_event(event)

    except KeyboardInterrupt:
        logger.warning("Shutdown signal received")
    finally:
        logger.info("Stopping services...")
        await bridge.stop()
        await db_writer.stop()
        await repo.close()
        logger.info("Shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
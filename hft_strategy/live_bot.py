# hft_strategy/live_bot.py
import asyncio
import logging
import sys
import os
from typing import Dict, Set
from dotenv import load_dotenv

# --- PATH HACK (Оставляем для совместимости с C++ модулем) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

build_path_release = os.path.join(project_root, "hft_core", "build", "Release")
if os.path.exists(build_path_release):
    if build_path_release not in sys.path:
        sys.path.insert(0, build_path_release)
# -------------------------------------------------------------

import hft_core 
from hft_strategy.config import TRADING_CONFIG
from hft_strategy.infrastructure.market_bridge import MarketBridge
from hft_strategy.infrastructure.execution import BybitExecutionHandler
from hft_strategy.domain.strategy_config import get_config
from hft_strategy.strategies.adaptive_live_strategy import AdaptiveWallStrategy

# [NEW] Импортируем наши новые компоненты
from hft_strategy.infrastructure.db_writer import NullTickWriter
from hft_strategy.services.smart_scanner import SmartMarketSelector

load_dotenv()

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
# Уменьшаем шум от библиотек
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("pybit").setLevel(logging.WARNING)

logger = logging.getLogger("ORCHESTRATOR")

# Конфигурация цикла ротации
ROTATION_INTERVAL_SEC = 300  # 5 минут
TOP_COINS_COUNT = 5

class BotOrchestrator:
    """
    Управляет жизненным циклом торговых стратегий.
    Реализует паттерн Orchestrator: выбирает активы, выделяет ресурсы, запускает/останавливает торговлю.
    """
    def __init__(self):
        self.api_key = os.getenv("BYBIT_API_KEY", "")
        self.api_secret = os.getenv("BYBIT_API_SECRET", "")
        
        if not self.api_key:
            logger.warning("⚠️ Running in ANONYMOUS mode (No Trading, just Scanning)")

        # 1. Инфраструктура
        # Используем NullWriter - запись в БД отключена (Goal 1 achieved)
        self.db_writer = NullTickWriter()
        
        # Executor (Один экземпляр на всех)
        self.executor = BybitExecutionHandler(self.api_key, self.api_secret, sandbox=False)
        
        # Scanner (Сервис выбора монет)
        self.scanner = SmartMarketSelector(self.executor)
        
        # Очередь событий и Event Loop
        self.loop = asyncio.get_running_loop()
        self.shared_queue = asyncio.Queue()
        
        # 2. C++ Core Components (WebSockets)
        self.pub_parser = hft_core.BybitParser()
        self.pub_streamer = hft_core.ExchangeStreamer(self.pub_parser)
        
        # Public Bridge (Market Data)
        self.public_bridge = MarketBridge(
            TRADING_CONFIG.ws_url, 
            self.pub_streamer, 
            self.loop, 
            queue=self.shared_queue
        )
        
        # Private Bridge (Executions)
        self.priv_bridge = None
        if self.api_key:
            self.priv_parser = hft_core.BybitParser()
            self.priv_streamer = hft_core.ExchangeStreamer(self.priv_parser)
            self.priv_bridge = MarketBridge(
                TRADING_CONFIG.private_ws_url, 
                self.priv_streamer, 
                self.loop, 
                queue=self.shared_queue
            )

        # State (Текущий портфель)
        self.active_strategies: Dict[str, AdaptiveWallStrategy] = {}
        self.active_symbols: Set[str] = set()
        self.is_running = True

    async def start_infrastructure(self):
        """Запуск сетевого слоя"""
        logger.info("🔌 Starting Infrastructure...")
        await self.db_writer.start()
        await self.public_bridge.start()
        
        if self.priv_bridge:
            await self.priv_bridge.start()
            self.priv_bridge.authenticate(self.api_key, self.api_secret)
            self.priv_bridge.subscribe_executions()
            
        # Запускаем обработчик очереди (Consumer) в фоне
        asyncio.create_task(self._event_processing_loop())

    async def _event_processing_loop(self):
        """
        Единый цикл обработки событий.
        Читает очередь и маршрутизирует данные в нужную стратегию.
        """
        logger.info("🌀 Event Processing Loop Active")
        while self.is_running:
            try:
                # Блокирующее чтение из очереди
                event = await self.shared_queue.get()
                
                # Запись в БД (в данном случае - в пустоту, т.к. NullWriter)
                await self.db_writer.add_event(event)

                # Маршрутизация (Routing)
                target_strat = self.active_strategies.get(event.symbol)
                if target_strat:
                    evt_type = getattr(event, 'type', 'unknown')
                    
                    if evt_type == 'depth':
                        # Обработка стакана
                        await target_strat.on_depth(event)
                    
                    elif evt_type == 'execution':
                        # Обработка сделки (Вход/Выход)
                        await target_strat.on_execution(event)
                        
            except Exception as e:
                logger.error(f"💥 Event Loop Error: {e}", exc_info=True)

    async def rotate_portfolio(self):
        """
        Основная логика ротации (Goal 2 achieved).
        Запрашивает новые монеты, обновляет стратегии и подписки.
        """
        logger.info("🔄 --- ROTATION CYCLE START ---")
        
        # 1. Smart Selection
        new_top_symbols = await self.scanner.scan_and_select(top_n=TOP_COINS_COUNT)
        
        if not new_top_symbols:
            logger.warning("⚠️ Scanner found nothing. Holding positions.")
            return

        new_set = set(new_top_symbols)
        
        # 2. Diff Calculation
        to_add = new_set - self.active_symbols
        to_remove = self.active_symbols - new_set
        
        if not to_add and not to_remove:
            logger.info("✨ Portfolio is stable. No rotation needed.")
            return

        logger.info(f"📉 Dropping: {list(to_remove)}")
        logger.info(f"📈 Adding:   {list(to_add)}")

        # 3. Удаление старых стратегий (Cleanup)
        for sym in to_remove:
            if sym in self.active_strategies:
                # В будущем здесь можно добавить strategy.graceful_stop()
                del self.active_strategies[sym]
        
        self.active_symbols -= to_remove

        # 4. Инициализация новых стратегий (Factory)
        for sym in to_add:
            try:
                # Получаем параметры инструмента (шаг цены, лотность)
                tick_size, lot_size, min_qty = await self.executor.fetch_instrument_info(sym)
                
                cfg = get_config(sym)
                cfg.tick_size = tick_size
                cfg.lot_size = lot_size
                cfg.min_qty = min_qty
                
                # Создаем и сохраняем стратегию
                new_strat = AdaptiveWallStrategy(self.executor, cfg)
                self.active_strategies[sym] = new_strat
                logger.info(f"✅ Armed strategy for {sym}")
                
            except Exception as e:
                logger.error(f"❌ Failed to init {sym}: {e}")
                continue

        # Обновляем кэш активных символов
        self.active_symbols = set(self.active_strategies.keys())

        # 5. Обновляем подписки Websocket (Bridge сам отпишется от старых и подпишется на новые)
        if self.active_symbols:
            await self.public_bridge.sync_heavy_subscriptions(list(self.active_symbols))
        
        logger.info(f"Current Portfolio ({len(self.active_symbols)}): {list(self.active_symbols)}")

    async def run_forever(self):
        """Главный цикл жизни бота"""
        await self.start_infrastructure()
        
        while self.is_running:
            try:
                # Запускаем ротацию
                await self.rotate_portfolio()
                
                # Ждем следующего цикла (Sleep interruptible)
                logger.info(f"💤 Sleeping for {ROTATION_INTERVAL_SEC}s...")
                for _ in range(ROTATION_INTERVAL_SEC):
                    if not self.is_running: break
                    await asyncio.sleep(1)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"🔥 Critical Orchestrator Error: {e}", exc_info=True)
                await asyncio.sleep(60) # Пауза перед рестартом при ошибке

    async def stop(self):
        """Корректное завершение"""
        logger.info("🛑 Stopping Orchestrator...")
        self.is_running = False
        
        await self.public_bridge.stop()
        if self.priv_bridge:
            await self.priv_bridge.stop()
            
        await self.db_writer.stop()
        logger.info("👋 Shutdown Complete.")

async def main():
    # Windows Selector Fix
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    bot = BotOrchestrator()
    try:
        await bot.run_forever()
    except KeyboardInterrupt:
        await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())
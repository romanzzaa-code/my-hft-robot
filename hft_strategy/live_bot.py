# hft_strategy/live_bot.py

# --- RUNTIME OPTIMIZATIONS (HFT CRITICAL) ---
# 1. uvloop: Ускорение Event Loop в 2-4x (libuv wrapper, как в Node.js)
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    print("🚀 uvloop enabled")
except ImportError:
    print("⚠️ uvloop not installed, using default asyncio loop")

# 2. gc: Управление сборщиком мусора для предотвращения stop-the-world пауз
import gc

import asyncio
import logging
from logging.handlers import TimedRotatingFileHandler
import signal
import sys
import os
import copy
from typing import List, Dict, Set, Optional, Union, Any

# --- PATH HACK ---
sys.path.append(os.getcwd())

# Импорт C++ ядра
try:
    import hft_core
except ImportError:
    print("❌ Critical: hft_core not found. Did you run 'pip install .' ?")
    sys.exit(1)

from hft_strategy.config import load_config, Config
from hft_strategy.infrastructure.execution import BybitExecutionHandler
from hft_strategy.services.smart_scanner import SmartMarketSelector
from hft_strategy.strategies.adaptive_live_strategy import AdaptiveWallStrategy
from hft_strategy.services.notification import TelegramNotifier

# --- CONSTANTS ---
RESCAN_INTERVAL_SEC = 300  # 5 минут между переоценкой рынка
MAX_COINS_TO_TRADE = 3     # Сколько монет торгуем одновременно

def setup_logging(config: Config):
    # 1. Папка для логов
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "hft_bot.log")

    # 2. Формат (добавил миллисекунды для HFT точности)
    formatter = logging.Formatter(
        '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 3. Хендлер для ФАЙЛА (Ротация раз в неделю, храним 4 недели)
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when='W0',        # W0 = Понедельник
        interval=1,       # Каждую 1 неделю
        backupCount=4,    # Хранить 4 файла (месяц)
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # 4. Хендлер для КОНСОЛИ (Чтобы ты видел это глазами прямо сейчас)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)

    # 5. Применяем настройки
    logging.basicConfig(
        level=config.log_level,
        handlers=[file_handler, stream_handler], 
        force=True 
    )
    
    # Глушим шум библиотек
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("pybit").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("ixwebsocket").setLevel(logging.WARNING)

class BotOrchestrator:
    def __init__(self, config_path_dummy: str):
        # 1. Загружаем базовый конфиг
        self.config = load_config()
        setup_logging(self.config)
        self.logger = logging.getLogger("BotOrchestrator")
        
        self.running = False
        self.loop = None
        self.notifier: Optional[TelegramNotifier] = None
        
        # Словарь для хранения стратегий: Symbol -> StrategyInstance
        self.strategies: Dict[str, AdaptiveWallStrategy] = {}
        
        # 2. Инициализация C++ Order Gateway
        self.logger.info("🔌 Initializing C++ Order Gateway...")
        try:
            self.gateway = hft_core.OrderGateway(
                self.config.api_key, 
                self.config.api_secret, 
                self.config.testnet
            )
            self.gateway.set_on_order_update(self._on_gateway_message)
            self.logger.info("✅ Gateway initialized.")
        except Exception as e:
            self.logger.critical(f"❌ Failed to init Gateway: {e}")
            sys.exit(1)

        # 3. Инициализация Market Data (C++)
        self.logger.info("📡 Initializing Exchange Streamer...")
        self.streamer = hft_core.ExchangeStreamer(hft_core.BybitParser())
        
        # 4. Execution Handler (HTTP REST)
        self.execution_handler = BybitExecutionHandler(
            api_key=self.config.api_key,
            api_secret=self.config.api_secret,
            sandbox=self.config.testnet
        )

        # 5. Smart Scanner
        self.smart_scanner = SmartMarketSelector(self.execution_handler)

    async def _find_best_assets(self, limit: int) -> List[str]:
        """Фаза разведки: ищем ТОП-N монет."""
        try:
            candidates = await self.smart_scanner.scan_and_select(top_n=limit)
            if not candidates:
                self.logger.warning("⚠️ Scanner found nothing. Keep calm.")
                return []
            return candidates
        except Exception as e:
            self.logger.error(f"Scan failed: {e}")
            return []

    # --- ROUTING DISPATCHERS (Маршрутизаторы) ---
    def _dispatch_tick(self, tick_data):
        """
        Универсальный диспетчер.
        Принимает как одиночный тик (Legacy C++), так и батч (Optimized C++).
        Гарантирует отсутствие падения при обновлении ядра.
        """
        # Проверяем, пришел ли нам список (новый C++)
        if isinstance(tick_data, list):
            # ОПТИМИЗАЦИЯ: Группируем тики по символам для снижения Overhead
            # Это уменьшает количество lookup'ов в self.strategies в N раз
            grouped_ticks = {}
            for tick in tick_data:
                if tick.symbol not in grouped_ticks:
                    grouped_ticks[tick.symbol] = []
                grouped_ticks[tick.symbol].append(tick)
            
            # Рассылаем уже сгруппированные пачки
            for symbol, batch in grouped_ticks.items():
                if symbol in self.strategies:
                    strategy = self.strategies[symbol]
                    # Если стратегия умеет принимать батчи - кидаем батч (идеально)
                    if hasattr(strategy, 'on_tick_batch'):
                        strategy.on_tick_batch(batch)
                    else:
                        # Иначе скармливаем по одному (совместимость)
                        for t in batch:
                            strategy.on_tick(t)
        else:
            # Старый режим (один тик) - работает как вчера
            tick = tick_data
            if tick.symbol in self.strategies:
                self.strategies[tick.symbol].on_tick(tick)

    def _dispatch_depth(self, snapshot):
        if snapshot.symbol in self.strategies and self.loop:
            asyncio.run_coroutine_threadsafe(
                self.strategies[snapshot.symbol].on_depth(snapshot),
                self.loop
            )

    def _dispatch_execution(self, exec_data):
        if exec_data.symbol in self.strategies and self.loop:
            asyncio.run_coroutine_threadsafe(
                self.strategies[exec_data.symbol].on_execution(exec_data),
                self.loop
            )

    def _setup_streamer_routing(self):
        self.streamer.set_tick_callback(self._dispatch_tick)
        self.streamer.set_orderbook_callback(self._dispatch_depth)
        self.streamer.set_execution_callback(self._dispatch_execution)

    def _on_gateway_message(self, msg: str):
        if "error" in msg.lower() and "retCode" not in msg:
             self.logger.error(f"⚡ GW ERROR: {msg}")

    # --- LIFECYCLE MANAGEMENT ---
    
    async def _activate_strategy(self, symbol: str):
        """Создает и запускает стратегию для новой монеты"""
        if symbol in self.strategies:
            return 

        self.logger.info(f"✨ Spawning strategy for {symbol}...")
        
        # 1. Клонируем конфиг
        strat_cfg = copy.copy(self.config.strategy)
        strat_cfg.symbol = symbol
        
        # Получаем спецификацию с биржи
        try:
            tick_size, step_size, min_qty = await self.execution_handler.fetch_instrument_info(symbol)
            strat_cfg.tick_size = tick_size
            strat_cfg.lot_size = step_size
            strat_cfg.min_qty = min_qty
            self.logger.info(f"📏 {symbol} Specs: Tick={tick_size}, Lot={step_size}")
        except Exception as e:
            self.logger.error(f"❌ Failed to fetch specs for {symbol}: {e}")
            return 
        
        # 2. Создаем стратегию
        # [FIX] Передаем notifier внутрь стратегии
        strategy = AdaptiveWallStrategy(
            executor=self.execution_handler,
            cfg=strat_cfg,
            gateway=self.gateway,
            notifier=self.notifier 
        )
        
        # 3. Регистрируем
        self.strategies[symbol] = strategy
        
        # 4. Подписываем на стрим
        self.streamer.add_symbol(symbol)

    async def _deactivate_strategy(self, symbol: str):
        if symbol not in self.strategies:
            return

        strategy = self.strategies[symbol]
        
        if not getattr(strategy, "is_shutting_down", False):
            self.logger.info(f"🛑 Signal STOP for {symbol}. Waiting for active orders to clear...")
            if hasattr(strategy, "set_graceful_stop"):
                strategy.set_graceful_stop()
            else:
                strategy.is_shutting_down = True

    async def _rotation_loop(self):
        self.logger.info(f"🔄 Rotation Watchdog started (Interval: {RESCAN_INTERVAL_SEC}s)")
        
        while self.running:
            try:
                await asyncio.sleep(RESCAN_INTERVAL_SEC)
                # РУЧНОЙ СБОР МУСОРА (когда мы не торгуем или меняем монеты)
                # Безопасно делать раз в 5 минут
                gc.collect()
                self.logger.info("🕵️ Periodic Market Rescan triggered...")
                
                new_top_coins = await self._find_best_assets(limit=MAX_COINS_TO_TRADE)
                if not new_top_coins:
                    continue 

                current_coins = set(self.strategies.keys())
                new_set = set(new_top_coins)

                to_add = new_set - current_coins
                to_remove = current_coins - new_set
                to_keep = current_coins & new_set

                if not to_add and not to_remove:
                    self.logger.info("💤 No changes in market leadership. Maintaining positions.")
                    pass
                else:
                    self.logger.info(f"⚖️ Rebalancing: +{to_add} | -{to_remove} | Keeping: {to_keep}")

                    for coin in to_remove:
                        await self._deactivate_strategy(coin)

                    for coin in to_add:
                        await self._activate_strategy(coin)

                # Garbage Collector
                keys_to_purge = []
                for sym, strat in self.strategies.items():
                    if getattr(strat, "can_be_deleted", False):
                        keys_to_purge.append(sym)
                
                for sym in keys_to_purge:
                    self.logger.info(f"🗑️ {sym} is clean. Removing from memory.")
                    del self.strategies[sym]

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.exception(f"Rotation loop error: {e}")
                await asyncio.sleep(60)

    async def run(self):
        # ОТКЛЮЧАЕМ GC ПЕРЕД ЗАПУСКОМ (HFT critical)
        gc.disable()
        self.logger.info("🗑️ Automatic GC DISABLED for performance")

        # 1. Читаем настройки из переменных окружения
        tg_token = os.getenv("TG_NOTIFIER_TOKEN")
        chat_id = os.getenv("TG_CHAT_ID")

        # 2. Инициализируем нотификатор (если настройки есть)
        if tg_token and chat_id:
            self.notifier = TelegramNotifier(token=tg_token, chat_id=chat_id)
            await self.notifier.start() 
            self.logger.info(f"🔔 Notifications enabled for ID: {chat_id}")
        else:
            self.logger.warning("🔕 Notifications DISABLED (Token or ChatID missing)")

        # [FIX] Удален блок ошибочного создания TradeManager здесь. 
        # TradeManager создается внутри AdaptiveWallStrategy.

        self.running = True
        self.loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            self.loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))

        try:
            self._setup_streamer_routing()
            
            self.logger.info("🔗 Connecting Order Gateway...")
            self.gateway.connect()
            await asyncio.sleep(1.0)
            
            self.logger.info("🌊 Starting Data Stream...")
            self.streamer.start()

            self.logger.info("🚀 Doing Initial Market Scan...")
            top_coins = await self._find_best_assets(limit=MAX_COINS_TO_TRADE)
            
            if not top_coins:
                top_coins = [self.config.symbol]
                self.logger.warning(f"⚠️ Using fallback coin: {top_coins}")

            for coin in top_coins:
                await self._activate_strategy(coin)
            
            self.logger.info(f"✅ Bot is running on: {list(self.strategies.keys())}")

            rotation_task = asyncio.create_task(self._rotation_loop())

            while self.running:
                await asyncio.sleep(1)
            
            rotation_task.cancel()
            try:
                await rotation_task
            except asyncio.CancelledError:
                pass

        except asyncio.CancelledError:
            self.logger.info("Bot execution cancelled.")
        except Exception as e:
            self.logger.exception(f"Unexpected error: {e}")
        finally:
            if self.notifier:
                 await self.notifier.stop()
            await self.shutdown()

    async def shutdown(self):
        if not self.running: return 
        self.logger.info("🛑 Shutting down...")
        self.running = False
        
        if hasattr(self, 'streamer'): self.streamer.stop()
        if hasattr(self, 'gateway'): self.gateway.stop()
        
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    bot = BotOrchestrator("dummy")
    asyncio.run(bot.run())
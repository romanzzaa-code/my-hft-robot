# hft_strategy/live_bot.py
import asyncio
import logging
from logging.handlers import TimedRotatingFileHandler
import signal
import sys
import os
import copy
from typing import List, Dict, Set

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
        handlers=[file_handler, stream_handler], # <--- ВАЖНО: Оба хендлера здесь
        force=True # Перезаписать старые конфиги, если они были
    )
    
    # Глушим шум библиотек, чтобы видеть только свои сделки
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
    def _dispatch_tick(self, tick):
        if tick.symbol in self.strategies:
            # Тики обрабатываем синхронно (это быстро)
            self.strategies[tick.symbol].on_tick(tick)

    def _dispatch_depth(self, snapshot):
        if snapshot.symbol in self.strategies and self.loop:
            # ПЕРЕБРАСЫВАЕМ В ГЛАВНЫЙ ПОТОК ЧЕРЕЗ threadsafe
            asyncio.run_coroutine_threadsafe(
                self.strategies[snapshot.symbol].on_depth(snapshot),
                self.loop
            )

    def _dispatch_execution(self, exec_data):
        if exec_data.symbol in self.strategies and self.loop:
            # ПЕРЕБРАСЫВАЕМ В ГЛАВНЫЙ ПОТОК ЧЕРЕЗ threadsafe
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
            return # Уже работает

        self.logger.info(f"✨ Spawning strategy for {symbol}...")
        
        # 1. Клонируем конфиг
        strat_cfg = copy.copy(self.config.strategy)
        strat_cfg.symbol = symbol
        
        # [FIX] ЗАПРАШИВАЕМ СПЕЦИФИКАЦИЮ С БИРЖИ
        try:
            # Получаем реальный шаг цены и лота
            tick_size, step_size, min_qty = await self.execution_handler.fetch_instrument_info(symbol)
            
            # Обновляем конфиг стратегии
            strat_cfg.tick_size = tick_size
            strat_cfg.lot_size = step_size
            strat_cfg.min_qty = min_qty
            
            self.logger.info(f"📏 {symbol} Specs: Tick={tick_size}, Lot={step_size}")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to fetch specs for {symbol}: {e}")
            return # Не запускаем стратегию с кривым конфигом
        
        # 2. Создаем стратегию (теперь с правильным tick_size)
        strategy = AdaptiveWallStrategy(
            executor=self.execution_handler,
            cfg=strat_cfg,
            gateway=self.gateway
        )
        
        # 3. Регистрируем
        self.strategies[symbol] = strategy
        
        # 4. Подписываем на стрим
        self.streamer.add_symbol(symbol)

    async def _deactivate_strategy(self, symbol: str):
        """Останавливает стратегию и убирает из ротации"""
        if symbol not in self.strategies:
            return

        self.logger.info(f"💀 Killing strategy for {symbol} (Dropped from Top)...")
        
        # 1. Получаем объект стратегии
        # strategy = self.strategies[symbol]
        
        # 2. Здесь можно вызвать strategy.shutdown(), если он есть
        # Но главное - убрать из словаря, чтобы Routing Dispatcher перестал слать туда данные
        del self.strategies[symbol]
        
        # 3. Отписываться в C++ (remove_symbol) пока не обязательно, 
        # диспетчер просто будет игнорировать лишние данные.
        # Но если метод есть, лучше вызвать: self.streamer.remove_symbol(symbol)

    async def _rotation_loop(self):
        """
        Фоновый процесс: каждые 5 минут пересматривает портфель
        """
        self.logger.info(f"🔄 Rotation Watchdog started (Interval: {RESCAN_INTERVAL_SEC}s)")
        
        while self.running:
            try:
                # Ждем интервал (используем wait_for чтобы прерываться при shutdown)
                await asyncio.sleep(RESCAN_INTERVAL_SEC)
                
                self.logger.info("🕵️ Periodic Market Rescan triggered...")
                
                # 1. Сканируем рынок
                new_top_coins = await self._find_best_assets(limit=MAX_COINS_TO_TRADE)
                if not new_top_coins:
                    continue # Если сканер упал, ничего не меняем

                current_coins = set(self.strategies.keys())
                new_set = set(new_top_coins)

                # 2. Вычисляем дельту
                to_add = new_set - current_coins
                to_remove = current_coins - new_set
                to_keep = current_coins & new_set

                if not to_add and not to_remove:
                    self.logger.info("💤 No changes in market leadership. Maintaining positions.")
                    continue

                self.logger.info(f"⚖️ Rebalancing: +{to_add} | -{to_remove} | Keeping: {to_keep}")

                # 3. Убираем слабых
                for coin in to_remove:
                    await self._deactivate_strategy(coin)

                # 4. Добавляем сильных
                for coin in to_add:
                    await self._activate_strategy(coin)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.exception(f"Rotation loop error: {e}")
                await asyncio.sleep(60) # Пауза перед ретраем при ошибке

    async def run(self):
        self.running = True
        
        self.loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            self.loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))

        try:
            # Настройка роутинга
            self._setup_streamer_routing()
            
            # Подключение к шлюзу
            self.logger.info("🔗 Connecting Order Gateway...")
            self.gateway.connect()
            await asyncio.sleep(1.0)
            
            # Запуск потока данных
            self.logger.info("🌊 Starting Data Stream...")
            self.streamer.start()

            # --- INITIAL ALLOCATION ---
            self.logger.info("🚀 Doing Initial Market Scan...")
            top_coins = await self._find_best_assets(limit=MAX_COINS_TO_TRADE)
            
            # Если сканер ничего не нашел при старте - берем дефолт из конфига
            if not top_coins:
                top_coins = [self.config.symbol]
                self.logger.warning(f"⚠️ Using fallback coin: {top_coins}")

            for coin in top_coins:
                await self._activate_strategy(coin)
            
            self.logger.info(f"✅ Bot is running on: {list(self.strategies.keys())}")

            # --- START ROTATION LOOP ---
            # Запускаем фоновую задачу ротации
            rotation_task = asyncio.create_task(self._rotation_loop())

            # Главный цикл (просто держит процесс живым)
            while self.running:
                await asyncio.sleep(1)
            
            # Ожидаем завершения ротации при выходе
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
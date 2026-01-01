import asyncio
import logging
import signal
import sys
from typing import Optional

# Импорт C++ ядра (убедись, что hft_core.so/pyd виден Python-у)
import hft_core

from hft_strategy.config import load_config, Config
from hft_strategy.infrastructure.execution import BybitExecutionHandler
from hft_strategy.services.market_scanner import MarketScanner
from hft_strategy.strategies.adaptive_live_strategy import AdaptiveWallStrategy

# Настройка логирования
def setup_logging(config: Config):
    logging.basicConfig(
        level=config.log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

class BotOrchestrator:
    def __init__(self, config_path: str):
        self.config = load_config(config_path)
        setup_logging(self.config)
        self.logger = logging.getLogger("BotOrchestrator")
        
        self.running = False
        
        # --- 1. Инициализация C++ Order Gateway (НОВОЕ) ---
        self.logger.info("🔌 Initializing C++ Order Gateway...")
        try:
            self.gateway = hft_core.OrderGateway(
                self.config.api_key, 
                self.config.api_secret, 
                self.config.testnet
            )
            # Устанавливаем коллбек для логов от биржи (ордера, ошибки)
            self.gateway.set_on_order_update(self._on_gateway_message)
            self.logger.info("✅ Gateway initialized.")
        except Exception as e:
            self.logger.critical(f"❌ Failed to init Gateway: {e}")
            sys.exit(1)

        # --- 2. Инициализация Market Data (C++) ---
        self.logger.info("📡 Initializing Exchange Streamer...")
        self.streamer = hft_core.ExchangeStreamer(hft_core.BybitParser())
        
        # --- 3. Legacy Execution Handler (пока оставляем для баланса/позиций) ---
        self.execution_handler = BybitExecutionHandler(self.config)

        # --- 4. Market Scanner ---
        self.scanner = MarketScanner(self.execution_handler)

        # --- 5. Стратегия ---
        # ВАЖНО: Передаем gateway в стратегию
        self.logger.info(f"🧠 Initializing Strategy for {self.config.symbol}...")
        self.strategy = AdaptiveWallStrategy(
            symbol=self.config.symbol,
            execution_handler=self.execution_handler, # Старый HTTP (для совместимости)
            gateway=self.gateway,                     # <--- НОВЫЙ C++ ШЛЮЗ
            config=self.config.strategy
        )

        # Связываем стример со стратегией
        self._setup_streamer()

    def _setup_streamer(self):
        """Настройка коллбеков от C++ к Python"""
        # Тики
        self.streamer.set_tick_callback(self.strategy.on_tick)
        # Стакан
        self.streamer.set_orderbook_callback(self.strategy.on_depth)
        # Исполнения (свои сделки) - пока просто логируем или обновляем позицию
        self.streamer.set_execution_callback(self._on_execution)
        
        # Добавляем символ в подписку
        self.streamer.add_symbol(self.config.symbol)

    def _on_gateway_message(self, msg: str):
        """Обработка сообщений от OrderGateway (ответы биржи)"""
        # Тут можно парсить JSON и обновлять состояние ордеров в стратегии
        # Пока просто выводим для отладки
        if "error" in msg.lower() and "retCode" not in msg:
             self.logger.error(f"⚡ GW ERROR: {msg}")
        else:
             self.logger.info(f"⚡ GW: {msg}")

    def _on_execution(self, exec_data):
        self.logger.info(f"💰 EXECUTION: {exec_data.side} {exec_data.qty} @ {exec_data.price}")
        # Тут можно вызывать self.strategy.update_position(...)

    async def run(self):
        self.running = True
        
        # Обработка сигналов остановки (Ctrl+C)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))

        try:
            # 1. Подключаем Торговый Шлюз
            self.logger.info("🔗 Connecting Order Gateway (Trade Stream)...")
            self.gateway.connect()
            
            # Ждем 1.5 секунды на соединение и авторизацию (C++ делает это асинхронно)
            self.logger.info("⏳ Waiting for Gateway Auth...")
            await asyncio.sleep(1.5) 
            
            # 2. Запускаем Стример Данных
            self.logger.info("🌊 Starting Data Stream...")
            self.streamer.start()

            self.logger.info("🚀 BOT STARTED. Press Ctrl+C to stop.")
            
            # Основной цикл (Keep Alive)
            while self.running:
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            self.logger.info("Bot execution cancelled.")
        except Exception as e:
            self.logger.exception(f"Unexpected error: {e}")
        finally:
            await self.shutdown()

    async def shutdown(self):
        self.logger.info("🛑 Shutting down...")
        self.running = False
        
        self.logger.info("Killing Streamer...")
        self.streamer.stop()
        
        self.logger.info("Killing Gateway...")
        self.gateway.stop()
        
        self.logger.info("Bye.")
        # Останавливаем loop
        loop = asyncio.get_running_loop()
        loop.stop()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m hft_strategy.live_bot config.yaml")
        sys.exit(1)
        
    bot = BotOrchestrator(sys.argv[1])
    asyncio.run(bot.run())
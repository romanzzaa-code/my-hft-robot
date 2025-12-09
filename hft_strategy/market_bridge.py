import asyncio
import json
import logging
from typing import Optional

# Импортируем наш C++ модуль
# (Убедись, что hft_core доступен в PYTHONPATH или лежит рядом)
import hft_core

logger = logging.getLogger(__name__)

class MarketBridge:
    def __init__(self, target_symbol: str, loop: asyncio.AbstractEventLoop):
        """
        :param target_symbol: Символ для торговли (напр. 'BTCUSDT')
        :param loop: Ссылка на Event Loop (нужна для threadsafe вызовов)
        """
        self.symbol = target_symbol
        self.loop = loop
        
        # Очередь для передачи данных в Стратегию/БД
        self.tick_queue = asyncio.Queue()
        
        # --- C++ CORE SETUP ---
        # 1. Создаем парсер (Strategy Pattern)
        self._parser = hft_core.BybitParser()
        
        # 2. Создаем стример и внедряем парсер (Dependency Injection)
        self._streamer = hft_core.ExchangeStreamer(self._parser)
        
        # 3. Настраиваем коллбек
        self._streamer.set_callback(self._on_cpp_tick)
        
        logger.info(f"MarketBridge initialized for {self.symbol}")

    def _on_cpp_tick(self, tick):
        """
        ⚠️ ЭТОТ МЕТОД ВЫЗЫВАЕТСЯ ИЗ C++ ПОТОКА!
        Здесь нельзя делать await или долгие вычисления.
        """
        # Фильтрация по символу (на всякий случай)
        if tick.symbol == self.symbol:
            # Магия asyncio: безопасно кладем в очередь главного потока
            self.loop.call_soon_threadsafe(self.tick_queue.put_nowait, tick)

    async def start(self):
        """Запуск подключения"""
        url = "wss://stream.bybit.com/v5/public/linear"
        logger.info(f"Connecting to {url}...")
        
        # connect и start - это синхронные C++ методы, они быстрые
        self._streamer.connect(url)
        self._streamer.start()
        
        # Даем время на установку соединения
        await asyncio.sleep(1)
        
        # Отправляем подписку
        await self._subscribe()

    async def stop(self):
        """Остановка"""
        logger.info("Stopping streamer...")
        self._streamer.stop()

    async def _subscribe(self):
        """Формируем JSON для подписки на Bybit"""
        sub_msg = {
            "op": "subscribe",
            "args": [
                f"publicTrade.{self.symbol}"
            ]
        }
        msg_str = json.dumps(sub_msg)
        logger.info(f"Subscribing: {msg_str}")
        self._streamer.send_message(msg_str)

    async def get_tick(self):
        """
        Метод для стратегии: получить следующий тик.
        Это асинхронный генератор можно сделать, но пока просто get.
        """
        return await self.tick_queue.get()
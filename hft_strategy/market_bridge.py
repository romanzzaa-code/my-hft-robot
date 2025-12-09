# hft_strategy/market_bridge.py
import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

class MarketBridge:
    def __init__(self, target_symbol: str, streamer: Any, loop: asyncio.AbstractEventLoop):
        self.symbol = target_symbol
        self.loop = loop
        self.tick_queue = asyncio.Queue()
        
        # Внедренная зависимость (C++ модуль)
        self._streamer = streamer
        
        # [NEW] Регистрируем ДВА коллбека вместо одного
        # C++ дернет эти методы, когда придут данные
        self._streamer.set_tick_callback(self._on_cpp_tick)
        self._streamer.set_depth_callback(self._on_cpp_depth)
        
        logger.info(f"✅ MarketBridge initialized for {self.symbol} (Trades + OrderBook)")

    def _on_cpp_tick(self, tick):
        # Обертка для тика сделки
        if tick.symbol == self.symbol:
            # Добавляем тип события, чтобы различать в Python
            setattr(tick, 'type', 'trade') 
            self.loop.call_soon_threadsafe(self.tick_queue.put_nowait, tick)

    def _on_cpp_depth(self, snapshot):
        # Обертка для снимка стакана
        if snapshot.symbol == self.symbol:
            setattr(snapshot, 'type', 'depth')
            self.loop.call_soon_threadsafe(self.tick_queue.put_nowait, snapshot)

    async def start(self):
        # Используем публичный стрим Bybit
        url = "wss://stream.bybit.com/v5/public/linear"
        logger.info(f"Bridge connecting to {url}...")
        
        self._streamer.connect(url)
        self._streamer.start()
        
        # Даем время на установку соединения
        await asyncio.sleep(1)
        await self._subscribe()

    async def stop(self):
        logger.info("Stopping streamer...")
        self._streamer.stop()

    async def _subscribe(self):
        # [NEW] Подписываемся на ДВА канала: сделки и стакан (глубина 50)
        sub_msg = {
            "op": "subscribe",
            "args": [
                f"publicTrade.{self.symbol}",
                f"orderbook.50.{self.symbol}"
            ]
        }
        msg_str = json.dumps(sub_msg)
        logger.info(f"📤 Sending subscription: {msg_str}")
        self._streamer.send_message(msg_str)

    async def get_tick(self):
        return await self.tick_queue.get()
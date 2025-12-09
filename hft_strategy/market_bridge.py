# hft_strategy/market_bridge.py
import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

class MarketBridge:
    def __init__(self, target_symbol: str, streamer: Any, loop: asyncio.AbstractEventLoop):
        """
        Теперь мы принимаем streamer как зависимость (Dependency Injection).
        Type hint 'Any' используется, так как hft_core - это C++ модуль,
        но в идеале здесь был бы Protocol.
        """
        self.symbol = target_symbol
        self.loop = loop
        self.tick_queue = asyncio.Queue()
        
        # Внедренная зависимость
        self._streamer = streamer
        
        # Настраиваем коллбек на ВНЕДРЕННОМ стримере
        self._streamer.set_callback(self._on_cpp_tick)
        
        logger.info(f"✅ MarketBridge initialized for {self.symbol} with injected Streamer")

    def _on_cpp_tick(self, tick):
        # Логика коллбека осталась прежней — это ответственность моста
        if tick.symbol == self.symbol:
            self.loop.call_soon_threadsafe(self.tick_queue.put_nowait, tick)

    async def start(self):
        
        url = "wss://stream.bybit.com/v5/public/linear"
        logger.info(f"Bridge connecting to {url}...")
        
        self._streamer.connect(url)
        self._streamer.start()
        
        await asyncio.sleep(1)
        await self._subscribe()

    async def stop(self):
        logger.info("Stopping streamer...")
        self._streamer.stop()

    async def _subscribe(self):
        sub_msg = {
            "op": "subscribe",
            "args": [f"publicTrade.{self.symbol}"]
        }
        msg_str = json.dumps(sub_msg)
        self._streamer.send_message(msg_str)

    async def get_tick(self):
        return await self.tick_queue.get()
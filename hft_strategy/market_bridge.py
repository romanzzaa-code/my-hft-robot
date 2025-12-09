# hft_strategy/market_bridge.py
import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

class MarketBridge:
    # [DI] Внедряем ws_url через конструктор
    def __init__(self, target_symbol: str, ws_url: str, streamer: Any, loop: asyncio.AbstractEventLoop):
        self.symbol = target_symbol
        self.ws_url = ws_url  # <-- Сохраняем URL
        self.loop = loop
        self.tick_queue = asyncio.Queue()
        
        self._streamer = streamer
        
        self._streamer.set_tick_callback(self._on_cpp_tick)
        self._streamer.set_depth_callback(self._on_cpp_depth)
        
        logger.info(f"✅ MarketBridge initialized for {self.symbol}")

    # ... _on_cpp_tick и _on_cpp_depth без изменений ...
    def _on_cpp_tick(self, tick):
        if tick.symbol == self.symbol:
            setattr(tick, 'type', 'trade') 
            self.loop.call_soon_threadsafe(self.tick_queue.put_nowait, tick)

    def _on_cpp_depth(self, snapshot):
        if snapshot.symbol == self.symbol:
            setattr(snapshot, 'type', 'depth')
            self.loop.call_soon_threadsafe(self.tick_queue.put_nowait, snapshot)

    async def start(self):
        # [FIX] Используем внедренный URL, а не хардкод
        logger.info(f"Bridge connecting to {self.ws_url}...")
        
        self._streamer.connect(self.ws_url)
        self._streamer.start()
        
        await asyncio.sleep(1)
        await self._subscribe()

    # ... stop и _subscribe без изменений (но _subscribe использует self.symbol, что ок) ...
    async def stop(self):
        logger.info("Stopping streamer...")
        self._streamer.stop()

    async def _subscribe(self):
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
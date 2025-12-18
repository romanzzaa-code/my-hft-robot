# hft_strategy/infrastructure/market_bridge.py
import asyncio
import json
import logging
from typing import Any, List, Set

logger = logging.getLogger("BRIDGE")

class MarketBridge:
    def __init__(self, ws_url: str, streamer: Any, loop: asyncio.AbstractEventLoop):
        self.ws_url = ws_url
        self.streamer = streamer
        self.loop = loop
        
        self.tick_queue = asyncio.Queue()
        self.active_heavy_symbols: Set[str] = set() 
        
        self.streamer.set_tick_callback(self._on_cpp_tick)
        self.streamer.set_depth_callback(self._on_cpp_depth)
        
        # Для управления задачей пинга
        self._heartbeat_task = None
        
        logger.info("✅ MarketBridge initialized")

    def _on_cpp_tick(self, tick):
        if tick.symbol in self.active_heavy_symbols:
            setattr(tick, 'type', 'trade') 
            self.loop.call_soon_threadsafe(self.tick_queue.put_nowait, tick)

    def _on_cpp_depth(self, snapshot):
        if snapshot.symbol in self.active_heavy_symbols:
            setattr(snapshot, 'type', 'depth')
            self.loop.call_soon_threadsafe(self.tick_queue.put_nowait, snapshot)

    async def start(self):
        logger.info(f"Connecting to {self.ws_url}...")
        self.streamer.connect(self.ws_url)
        self.streamer.start()
        await asyncio.sleep(2)
        
        # [NEW] Запускаем сердцебиение (Heartbeat)
        if not self._heartbeat_task:
            self._heartbeat_task = asyncio.create_task(self._keep_alive_loop())
            logger.info("💓 Heartbeat task started")

    async def stop(self):
        # [NEW] Останавливаем пинги
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
            
        logger.info("Stopping streamer...")
        self.streamer.stop()

    # [NEW] Логика пинга для Bybit V5
    async def _keep_alive_loop(self):
        """
        Отправляет Application-Layer Ping каждые 20 секунд.
        Это предотвращает разрыв соединения со стороны Bybit (Error 10006/Disconnect).
        """
        while True:
            try:
                await asyncio.sleep(20)
                # Bybit требует именно такую структуру
                ping_payload = json.dumps({"op": "ping", "req_id": "keepalive"})
                self.streamer.send_message(ping_payload)
                # logger.debug("💓 Ping sent") # Раскомментируй для отладки
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
                await asyncio.sleep(5) # Пауза перед ретраем при ошибке

    # ... (Остальные методы subscribe_to_tickers, sync_heavy_subscriptions, _send_batch, get_tick 
    #      остаются БЕЗ ИЗМЕНЕНИЙ) ...

    async def subscribe_to_tickers(self, all_symbols: List[str]):
        if not all_symbols:
            return
        logger.info(f"📡 Subscribing scanner to {len(all_symbols)} tickers...")
        topics = [f"tickers.{sym}" for sym in all_symbols]
        await self._send_batch("subscribe", topics)

    async def sync_heavy_subscriptions(self, target_top_coins: List[str]):
        target_set = set(target_top_coins)
        to_subscribe = target_set - self.active_heavy_symbols
        to_unsubscribe = self.active_heavy_symbols - target_set
        
        if not to_subscribe and not to_unsubscribe:
            return 

        logger.info(f"🔄 Rotation: +{len(to_subscribe)} new, -{len(to_unsubscribe)} removed")

        if to_unsubscribe:
            topics = []
            for sym in to_unsubscribe:
                topics.append(f"publicTrade.{sym}")
                topics.append(f"orderbook.50.{sym}")
            await self._send_batch("unsubscribe", topics)
            self.active_heavy_symbols -= to_unsubscribe

        if to_subscribe:
            topics = []
            for sym in to_subscribe:
                topics.append(f"publicTrade.{sym}")
                topics.append(f"orderbook.50.{sym}")
            await self._send_batch("subscribe", topics)
            self.active_heavy_symbols.update(to_subscribe)
            
        logger.info(f"🔥 Active Heavy Streams: {self.active_heavy_symbols}")

    async def _send_batch(self, op: str, topics: List[str]):
        chunk_size = 10
        for i in range(0, len(topics), chunk_size):
            chunk = topics[i:i + chunk_size]
            payload = {
                "op": op,
                "args": chunk
            }
            self.streamer.send_message(json.dumps(payload))
            await asyncio.sleep(0.02) 

    async def get_tick(self):
        return await self.tick_queue.get()
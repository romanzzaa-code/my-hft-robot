# hft_strategy/infrastructure/market_bridge.py
import asyncio
import json
import logging
import hmac
import hashlib
import time
from typing import Any, List, Set, Optional

logger = logging.getLogger("BRIDGE")

class MarketBridge:
    def __init__(self, ws_url: str, streamer: Any, loop: asyncio.AbstractEventLoop, queue: Optional[asyncio.Queue] = None):
        """
        :param queue: Если передан, используется общая очередь (для слияния Public и Private потоков).
        """
        self.ws_url = ws_url
        self.streamer = streamer
        self.loop = loop
        
        # Dependency Injection для очереди
        self.tick_queue = queue if queue is not None else asyncio.Queue()
        
        self.active_heavy_symbols: Set[str] = set() 
        
        # Регистрируем коллбеки
        self.streamer.set_tick_callback(self._on_cpp_tick)
        self.streamer.set_depth_callback(self._on_cpp_depth)
        
        # [NEW] Регистрируем коллбек исполнений (если метод существует в C++)
        if hasattr(self.streamer, "set_execution_callback"):
            self.streamer.set_execution_callback(self._on_cpp_execution)
        
        self._heartbeat_task = None
        logger.info(f"✅ MarketBridge initialized for {ws_url}")

    # --- CALLBACKS ---
    def _on_cpp_tick(self, tick):
        # Фильтруем тики только для активных монет (чтобы не засорять очередь)
        if tick.symbol in self.active_heavy_symbols:
            setattr(tick, 'type', 'trade') 
            self.loop.call_soon_threadsafe(self.tick_queue.put_nowait, tick)

    def _on_cpp_depth(self, snapshot):
        if snapshot.symbol in self.active_heavy_symbols:
            setattr(snapshot, 'type', 'depth')
            self.loop.call_soon_threadsafe(self.tick_queue.put_nowait, snapshot)

    def _on_cpp_execution(self, exec_data):
        """
        [NEW] Обработка приватных исполнений.
        Сюда данные прилетают мгновенно (Push).
        """
        # Тегируем событие как 'execution'
        setattr(exec_data, 'type', 'execution')
        
        # Важно: Приватные события кладем в очередь ВСЕГДА (без фильтрации по active_heavy_symbols)
        # Это наши деньги, мы должны знать о них.
        self.loop.call_soon_threadsafe(self.tick_queue.put_nowait, exec_data)

    # --- LIFECYCLE ---
    async def start(self):
        logger.info(f"🔌 Connecting to {self.ws_url}...")
        self.streamer.connect(self.ws_url)
        self.streamer.start()
        
        # Даем время на установку соединения
        await asyncio.sleep(1)
        
        if not self._heartbeat_task:
            self._heartbeat_task = asyncio.create_task(self._keep_alive_loop())
            logger.info("💓 Heartbeat task started")

    async def stop(self):
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
            
        logger.info("💤 Stopping streamer...")
        self.streamer.stop()

    async def _keep_alive_loop(self):
        while True:
            try:
                await asyncio.sleep(20)
                ping_payload = json.dumps({"op": "ping", "req_id": "keepalive"})
                self.streamer.send_message(ping_payload)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
                await asyncio.sleep(5)

    # --- PUBLIC METHODS ---
    async def subscribe_to_tickers(self, all_symbols: List[str]):
        if not all_symbols: return
        logger.info(f"📡 Subscribing scanner to {len(all_symbols)} tickers...")
        topics = [f"tickers.{sym}" for sym in all_symbols]
        await self._send_batch("subscribe", topics)

    async def sync_heavy_subscriptions(self, target_top_coins: List[str]):
        # ... (Логика подписки на стаканы, без изменений, см. ниже)
        target_set = set(target_top_coins)
        to_subscribe = target_set - self.active_heavy_symbols
        to_unsubscribe = self.active_heavy_symbols - target_set
        
        if not to_subscribe and not to_unsubscribe: return 

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

    # --- [NEW] PRIVATE METHODS ---
    def authenticate(self, api_key: str, api_secret: str):
        """
        Отправляет AUTH пакет для Bybit V5.
        Вызывать сразу после start().
        """
        if not api_key or not api_secret:
            logger.warning("⚠️ No API keys provided. Skipping authentication.")
            return

        # Генерация подписи
        # Bybit требует expires (время в будущем в мс)
        expires = int((time.time() + 10) * 1000) 
        val = f"GET/realtime{expires}"
        
        signature = hmac.new(
            bytes(api_secret, "utf-8"),
            bytes(val, "utf-8"),
            hashlib.sha256
        ).hexdigest()
        
        payload = {
            "op": "auth",
            "args": [api_key, expires, signature]
        }
        
        logger.info("🔑 Authenticating Private Stream...")
        self.streamer.send_message(json.dumps(payload))

    def subscribe_executions(self):
        """
        Подписка на поток исполнений.
        """
        payload = {
            "op": "subscribe",
            "args": ["execution"]
        }
        self.streamer.send_message(json.dumps(payload))
        logger.info("🕵️ Subscribed to Private Executions")

    # --- UTILS ---
    async def _send_batch(self, op: str, topics: List[str]):
        chunk_size = 10
        for i in range(0, len(topics), chunk_size):
            chunk = topics[i:i + chunk_size]
            payload = {"op": op, "args": chunk}
            self.streamer.send_message(json.dumps(payload))
            await asyncio.sleep(0.02) 

    async def get_tick(self):
        return await self.tick_queue.get()
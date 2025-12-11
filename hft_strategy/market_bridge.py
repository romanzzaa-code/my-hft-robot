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
        
        # Очередь для передачи событий в DB Writer
        self.tick_queue = asyncio.Queue()
        
        # Состояние подписок
        self.active_heavy_symbols: Set[str] = set() # То, на что подписаны стаканы
        
        # Регистрируем коллбеки C++
        # Тикеры обрабатываются сканером напрямую (в main.py), сюда их не тащим
        self.streamer.set_tick_callback(self._on_cpp_tick)
        self.streamer.set_depth_callback(self._on_cpp_depth)
        
        logger.info("✅ MarketBridge initialized")

    def _on_cpp_tick(self, tick):
        # Пропускаем только если мы реально подписаны (защита от гонок данных)
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
        # Даем время на установку соединения перед отправкой команд
        await asyncio.sleep(2)

    async def stop(self):
        logger.info("Stopping streamer...")
        self.streamer.stop()

    # --- ЛЕГКИЙ РЕЖИМ (SCANNER) ---
    async def subscribe_to_tickers(self, all_symbols: List[str]):
        """
        Подписывается на канал 'tickers' для переданного списка монет.
        Это легкие данные для сканера.
        """
        if not all_symbols:
            return

        logger.info(f"📡 Subscribing scanner to {len(all_symbols)} tickers...")
        topics = [f"tickers.{sym}" for sym in all_symbols]
        await self._send_batch("subscribe", topics)

    # --- ТЯЖЕЛЫЙ РЕЖИМ (TRADER) ---
    async def sync_heavy_subscriptions(self, target_top_coins: List[str]):
        """
        Синхронизирует подписки на стаканы (orderbook.50 + publicTrade).
        Вычисляет разницу и отправляет только нужные команды (Subscribe/Unsubscribe).
        """
        target_set = set(target_top_coins)
        
        # 1. Что нужно добавить (Новые лидеры)
        to_subscribe = target_set - self.active_heavy_symbols
        
        # 2. Что нужно удалить (Вылетели из топа)
        to_unsubscribe = self.active_heavy_symbols - target_set
        
        if not to_subscribe and not to_unsubscribe:
            return # Изменений нет

        logger.info(f"🔄 Rotation: +{len(to_subscribe)} new, -{len(to_unsubscribe)} removed")

        # Сначала отписываемся, чтобы освободить канал
        if to_unsubscribe:
            topics = []
            for sym in to_unsubscribe:
                topics.append(f"publicTrade.{sym}")
                topics.append(f"orderbook.50.{sym}")
            await self._send_batch("unsubscribe", topics)
            self.active_heavy_symbols -= to_unsubscribe

        # Потом подписываемся
        if to_subscribe:
            topics = []
            for sym in to_subscribe:
                topics.append(f"publicTrade.{sym}")
                topics.append(f"orderbook.50.{sym}")
            await self._send_batch("subscribe", topics)
            self.active_heavy_symbols.update(to_subscribe)
            
        logger.info(f"🔥 Active Heavy Streams: {self.active_heavy_symbols}")

    async def _send_batch(self, op: str, topics: List[str]):
        """
        Отправляет команды пачками по 10 топиков (Limit Bybit).
        """
        chunk_size = 10
        for i in range(0, len(topics), chunk_size):
            chunk = topics[i:i + chunk_size]
            payload = {
                "op": op,
                "args": chunk
            }
            self.streamer.send_message(json.dumps(payload))
            # Микро-пауза, чтобы не зафлудить сокет
            await asyncio.sleep(0.02) 

    async def get_tick(self):
        return await self.tick_queue.get()
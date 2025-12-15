# hft_strategy/strategies/live_strategy.py
import logging
import asyncio
from hft_strategy.infrastructure.execution import BybitExecutionHandler
from hft_strategy.domain.strategy_config import StrategyParameters

logger = logging.getLogger("LIVE_STRAT")

class WallBounceLive:
    def __init__(self, executor: BybitExecutionHandler, cfg: StrategyParameters):
        self.exec = executor
        self.cfg = cfg
        self.active_buy_id = None
        
        # Rate Limiter (чтобы не забанили за спам логами)
        self.last_log_ts = 0

    async def on_depth(self, snapshot):
        """
        Принимает snapshot (C++ OrderBookSnapshot)
        """
        # Проверка валидности (иногда прилетают пустые)
        if not snapshot.bids or not snapshot.asks:
            return

        # 1. Данные
        best_bid = snapshot.bids[0].price
        best_bid_qty = snapshot.bids[0].quantity
        
        # 2. Логика (упрощенная для теста связи)
        is_wall = best_bid_qty >= self.cfg.wall_vol_threshold
        
        # Логируем только стены (раз в 1 сек, чтобы не флудить)
        now = asyncio.get_running_loop().time()
        if is_wall and (now - self.last_log_ts > 1.0):
            logger.info(f"🧱 WALL DETECTED: {best_bid_qty:.1f} lots @ {best_bid}")
            self.last_log_ts = now

        # 3. Действие (Вход)
        if is_wall and self.active_buy_id is None:
            price = round(best_bid + self.cfg.tick_size, 2)
            
            # Отправляем "виртуальный" ордер
            logger.info(f"🚀 SIGNAL: Front-run Wall at {price}")
            self.active_buy_id = await self.exec.place_limit_maker("Buy", price, self.cfg.order_qty)
            
            # Сразу "забываем" ордер через 5 сек для теста (эмуляция цикла)
            asyncio.create_task(self._reset_order_later(5))

    async def _reset_order_later(self, delay):
        await asyncio.sleep(delay)
        if self.active_buy_id:
            await self.exec.cancel_order(self.active_buy_id)
            self.active_buy_id = None
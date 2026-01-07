# hft_strategy/strategies/adaptive_live_strategy.py
import logging
import asyncio
import time
from typing import Optional

from hft_strategy.infrastructure.local_order_book import LocalOrderBook
from hft_strategy.domain.trade_context import StrategyState
from hft_strategy.domain.strategy_config import StrategyParameters
from hft_strategy.domain.interfaces import IExecutionHandler

# Наши новые сервисы
from hft_strategy.services.analytics import MarketAnalytics
from hft_strategy.services.wall_detector import WallDetector
from hft_strategy.services.trade_manager import TradeManager

logger = logging.getLogger("ORCHESTRATOR")

class AdaptiveWallStrategy:
    """
    Тонкий оркестратор стратегии. 
    Связывает воедино аналитику, поиск сигналов и управление сделками.
    """
    def __init__(self, 
                 executor: IExecutionHandler, 
                 cfg: StrategyParameters,
                 gateway: Optional[object] = None):
        
        self.cfg = cfg
        self.lob = LocalOrderBook()
        self._lock = asyncio.Lock()
        
        # 1. Инициализация сервисов (Композиция)
        self.analytics = MarketAnalytics(executor, cfg)
        self.detector = WallDetector(cfg)
        self.trade_manager = TradeManager(executor, cfg, gateway)
        
        # 2. Запуск фоновых задач
        asyncio.create_task(self.analytics.start())

    # --- СИСТЕМНЫЕ СОБЫТИЯ ---

    async def on_execution(self, event):
        """Проброс события исполнения в менеджер сделок"""
        await self.trade_manager.handle_execution(event)

    def on_tick(self, tick):
        """Тики используем только для быстрой сверки цены в будущем"""
        pass

    async def on_depth(self, snapshot):
        """Единый цикл обработки стакана"""
        if self._lock.locked(): return
        
        async with self._lock:
            # 1. Обновляем локальный стакан
            if hasattr(snapshot, 'bids') and not isinstance(snapshot.bids, dict):
                self.lob.apply_snapshot(snapshot)
            else:
                self.lob.apply_update(snapshot)
            
            if not self.lob.bids or not self.lob.asks: return

            # 2. Обновляем метрики волатильности и объема
            bg_vol = self.lob.get_background_volume()
            self.analytics.update_background_volume(bg_vol)

            # 3. ДИСПЕТЧЕРИЗАЦИЯ СОСТОЯНИЙ (FSM)
            state = self.trade_manager.state

            if state == StrategyState.IDLE:
                await self._process_idle()

            elif state == StrategyState.ORDER_PLACED:
                await self._process_order_placed()

            elif state == StrategyState.IN_POSITION:
                await self._process_in_position()

    # --- ЛОГИКА СОСТОЯНИЙ (Делегирование) ---

    async def _process_idle(self):
        """Поиск точки входа через WallDetector"""
        signal = self.detector.detect_signal(
            self.lob, 
            self.analytics.avg_background_vol
        )
        
        if signal:
            # Рассчитываем объем на основе настроек риска
            raw_qty = self.cfg.order_amount_usdt / signal["entry_price"]
            # Здесь можно добавить округление qty через хелпер, как было раньше
            
            await self.trade_manager.open_position(
                side=signal["side"],
                wall_price=signal["wall_price"],
                entry_price=signal["entry_price"],
                qty=raw_qty
            )

    async def _process_order_placed(self):
        """Контроль актуальности выставленного ордера"""
        ctx = self.trade_manager.ctx
        if not ctx: return

        # Проверка 1: Стена всё еще на месте?
        current_wall_v = self.lob.get_volume(ctx.side, ctx.wall_price)
        threshold = self.analytics.avg_background_vol * self.cfg.wall_ratio_threshold * 0.5
        
        wall_gone = current_wall_v < threshold
        # Проверка 2: Ордер не висит слишком долго?
        timed_out = (time.time() - ctx.placed_ts) > 15.0

        if wall_gone or timed_out:
            reason = "Wall collapsed" if wall_gone else "Timeout"
            logger.debug(f"🧱 {reason}. Cancelling entry...")
            await self.trade_manager.cancel_entry()

    async def _process_in_position(self):
        """Мониторинг открытой позиции (Stop Loss и Wall Breakout)"""
        ctx = self.trade_manager.ctx
        if not ctx or ctx.filled_qty <= 1e-9: return

        best_bid = self.lob.get_best("Buy")
        best_ask = self.lob.get_best("Sell")
        
        # Цена, по которой мы будем выходить в панике
        exit_price = best_bid if ctx.side == "Buy" else best_ask
        
        # 1. Расчет PnL в тиках
        delta = (exit_price - ctx.entry_price) if ctx.side == "Buy" else (ctx.entry_price - exit_price)
        pnl_ticks = delta / self.cfg.tick_size
        
        # 2. Условие пробоя стены
        wall_broken = (exit_price < ctx.wall_price) if ctx.side == "Buy" else (exit_price > ctx.wall_price)
        
        # 3. Условие жесткого стоп-лосса
        stop_hit = pnl_ticks <= -self.cfg.stop_loss_ticks

        if wall_broken or stop_hit:
            reason = "WALL BREACH" if wall_broken else "STOP LOSS"
            logger.warning(f"🚨 {reason} ({pnl_ticks:.1f} ticks). Exiting now!")
            await self.trade_manager.panic_exit()
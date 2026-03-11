use crate::{
    LocalOrderBook, MarketAnalytics, StrategyParameters, StrategyState, 
    TradeContext, WallDetector, Side, Tick, Price, Qty
};
use chrono::Utc;
use rust_decimal::Decimal;
// use tracing::error; // Removed as requested

pub struct AdaptiveWallStrategyLogic {
    pub params: StrategyParameters,
    pub state: StrategyState,
    pub ctx: Option<TradeContext>,
    pub lob: LocalOrderBook,
    pub analytics: MarketAnalytics,
    pub detector: WallDetector,
}

#[derive(Debug)]
pub enum StrategyAction {
    OpenPosition {
        side: Side,
        wall_price: Price,
        entry_price: Price,
        qty: Qty,
        stop_loss: Price,
        take_profit: Price,
    },
    CancelEntry {
        order_id: String,
        reason: String,
    },
    PanicExit {
        order_id: String,
        qty: Qty,
        reason: String,
    },
    None,
}

impl AdaptiveWallStrategyLogic {
    pub fn new(params: StrategyParameters) -> Self {
        Self {
            params,
            state: StrategyState::Idle,
            ctx: None,
            lob: LocalOrderBook::new(),
            analytics: MarketAnalytics::new(),
            detector: WallDetector::new(3),
        }
    }

    pub fn on_tick(&mut self, tick: &Tick) -> StrategyAction {
        if self.state == StrategyState::OrderPlaced {
            if let Some(ctx) = &self.ctx {
                let is_break = match ctx.side {
                    Side::Buy => {
                        if self.params.entry_touch_tolerance {
                            tick.price < ctx.wall_price
                        } else {
                            tick.price <= ctx.wall_price
                        }
                    }
                    Side::Sell => {
                        if self.params.entry_touch_tolerance {
                            tick.price > ctx.wall_price
                        } else {
                            tick.price >= ctx.wall_price
                        }
                    }
                };

                if is_break {
                    if let Some(order_id) = &ctx.order_id {
                        return StrategyAction::CancelEntry {
                            order_id: order_id.clone(),
                            reason: format!("Tick Break {}", tick.price),
                        };
                    }
                }
            }
        }
        StrategyAction::None
    }

    pub fn on_orderbook(&mut self, bids: Vec<(Price, Qty)>, asks: Vec<(Price, Qty)>, is_snapshot: bool) -> StrategyAction {
        self.lob.apply_update(bids, asks, is_snapshot);
        
        let bg_vol = self.lob.get_background_volume();
        self.analytics.update_background_volume(bg_vol, self.params.vol_ema_alpha);

        match self.state {
            StrategyState::Idle => self.process_idle(),
            StrategyState::OrderPlaced => self.process_order_placed(),
            StrategyState::InPosition => self.process_in_position(),
            _ => StrategyAction::None,
        }
    }

    fn process_idle(&mut self) -> StrategyAction {
        if let Some(signal) = self.detector.detect_signal(&self.lob, self.analytics.avg_background_vol, &self.params) {
            let entry_price = signal.entry_price;
            let raw_qty = self.params.order_amount_usdt / entry_price;
            let qty = (raw_qty / self.params.lot_size).floor() * self.params.lot_size;

            if qty < self.params.min_qty {
                return StrategyAction::None;
            }

            let (tp, sl) = self.analytics.calculate_exits(signal.side, entry_price, signal.wall_price, &self.params);

            StrategyAction::OpenPosition {
                side: signal.side,
                wall_price: signal.wall_price,
                entry_price,
                qty,
                stop_loss: sl,
                take_profit: tp,
            }
        } else {
            StrategyAction::None
        }
    }

    fn process_order_placed(&mut self) -> StrategyAction {
        let ctx = match &self.ctx {
            Some(c) => c,
            None => return StrategyAction::None,
        };

        let current_wall_v = self.lob.get_volume(ctx.side, ctx.wall_price);
        // Порог отмены ордера: 40% от требуемой стены
        let threshold = self.analytics.avg_background_vol * self.params.wall_ratio_threshold * rust_decimal_macros::dec!(0.4);
        let wall_collapsed = current_wall_v < threshold;

        let best_bid = self.lob.get_best(Side::Buy).unwrap_or(Decimal::ZERO);
        let best_ask = self.lob.get_best(Side::Sell).unwrap_or(Decimal::ZERO);

        let price_ran_away = match ctx.side {
            Side::Buy => best_bid > (ctx.entry_price + Decimal::from(5) * self.params.tick_size),
            Side::Sell => best_ask < (ctx.entry_price - Decimal::from(5) * self.params.tick_size),
        };

        let timed_out = (Utc::now() - ctx.placed_at).num_seconds() > 30;

        if wall_collapsed || price_ran_away || timed_out {
            let reason = if wall_collapsed { "Wall Collapsed" } else if price_ran_away { "Price Runaway" } else { "Timeout" };
            if let Some(order_id) = &ctx.order_id {
                return StrategyAction::CancelEntry {
                    order_id: order_id.clone(),
                    reason: reason.to_string(),
                };
            }
        }

        StrategyAction::None
    }

    fn process_in_position(&mut self) -> StrategyAction {
        let ctx = match &self.ctx {
            Some(c) => c,
            None => return StrategyAction::None,
        };

        let current_wall_v = self.lob.get_volume(ctx.side, ctx.wall_price);
        // Порог панического выхода: 30% от требуемой стены (чуть жестче чем при входе)
        let threshold = self.analytics.avg_background_vol * self.params.wall_ratio_threshold * rust_decimal_macros::dec!(0.3);
        let wall_collapsed = current_wall_v < threshold;

        let best_bid = self.lob.get_best(Side::Buy).unwrap_or(Decimal::ZERO);
        let best_ask = self.lob.get_best(Side::Sell).unwrap_or(Decimal::ZERO);

        let exit_price = match ctx.side {
            Side::Buy => best_bid,
            Side::Sell => best_ask,
        };

        let limit_p = match ctx.side {
            Side::Buy => ctx.wall_price - Decimal::from(self.params.exit_wall_tolerance_ticks) * self.params.tick_size,
            Side::Sell => ctx.wall_price + Decimal::from(self.params.exit_wall_tolerance_ticks) * self.params.tick_size,
        };

        let price_broken = match ctx.side {
            Side::Buy => exit_price < limit_p,
            Side::Sell => exit_price > limit_p,
        };

        let delta = if ctx.side == Side::Buy { exit_price - ctx.entry_price } else { ctx.entry_price - exit_price };
        let pnl_ticks = delta / self.params.tick_size;
        let stop_hit = pnl_ticks <= -Decimal::from(self.params.stop_loss_ticks);

        if wall_collapsed || price_broken || stop_hit {
            let reason = if wall_collapsed { "Wall Collapsed" } else if price_broken { "Wall Broken (Price)" } else { "Hard Stop Hit" };
            if let Some(order_id) = &ctx.order_id {
                return StrategyAction::PanicExit {
                    order_id: order_id.clone(),
                    qty: ctx.filled_qty,
                    reason: reason.to_string(),
                };
            }
        }

        StrategyAction::None
    }

    pub fn update_state(&mut self, action: &StrategyAction) {
        match action {
            StrategyAction::OpenPosition { side, wall_price, entry_price, qty, stop_loss, take_profit } => {
                self.state = StrategyState::OrderPlaced;
                self.ctx = Some(TradeContext {
                    side: *side,
                    wall_price: *wall_price,
                    entry_price: *entry_price,
                    qty: *qty,
                    stop_loss: *stop_loss,
                    take_profit: *take_profit,
                    placed_at: Utc::now(),
                    order_id: None, // Will be set by runner
                    filled_qty: Decimal::ZERO,
                    avg_fill_price: None,
                });
            }
            StrategyAction::CancelEntry { .. } | StrategyAction::PanicExit { .. } => {
                // Runner will handle the actual reset after confirming with exchange if needed,
                // or we can optimisticly reset here.
            }
            StrategyAction::None => {}
        }
    }

    pub fn reset(&mut self) {
        self.state = StrategyState::Idle;
        self.ctx = None;
    }
}

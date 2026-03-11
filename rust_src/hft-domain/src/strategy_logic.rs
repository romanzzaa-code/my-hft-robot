use crate::{
    LocalOrderBook, MarketAnalytics, StrategyParameters, StrategyState, 
    TradeContext, WallDetector, Side, Tick, Price, Qty
};
use chrono::Utc;
use rust_decimal::Decimal;

pub struct AdaptiveWallStrategyLogic {
    pub params: StrategyParameters,
    pub state: StrategyState,
    pub ctx: Option<TradeContext>,
    pub lob: LocalOrderBook,
    pub analytics: MarketAnalytics,
    pub detector: WallDetector,
}

#[derive(Debug, Clone)]
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
        side: Side,
        order_id: String,
        qty: Qty,
        reason: String,
    },
    RequestStatusUpdate {
        order_id: String,
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
                // Throttle retries if previous action failed (Backoff)
                if let Some(last_action) = ctx.last_action_at {
                    if (Utc::now() - last_action).num_milliseconds() < self.params.retry_backoff_ms {
                        return StrategyAction::None;
                    }
                }

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
        let ctx = match &mut self.ctx {
            Some(c) => c,
            None => return StrategyAction::None,
        };

        let now = Utc::now();
        // Backoff check
        if let Some(last_action) = ctx.last_action_at {
            if (now - last_action).num_milliseconds() < self.params.retry_backoff_ms {
                return StrategyAction::None;
            }
        }

        // Fallback check if execution report is missed
        let time_since_query = (now - ctx.last_queried_at.unwrap_or(ctx.placed_at)).num_seconds();
        if time_since_query >= 5 {
            if let Some(order_id) = &ctx.order_id {
                ctx.last_queried_at = Some(now);
                return StrategyAction::RequestStatusUpdate { order_id: order_id.clone() };
            }
        }

        let current_wall_v = self.lob.get_volume(ctx.side, ctx.wall_price);
        let threshold = self.analytics.avg_background_vol * self.params.wall_ratio_threshold * self.params.cancel_wall_ratio;
        let wall_collapsed = current_wall_v < threshold;

        let best_bid = self.lob.get_best(Side::Buy).unwrap_or(Decimal::ZERO);
        let best_ask = self.lob.get_best(Side::Sell).unwrap_or(Decimal::ZERO);

        let price_ran_away = match ctx.side {
            Side::Buy => best_bid > (ctx.entry_price + Decimal::from(self.params.price_runaway_ticks) * self.params.tick_size),
            Side::Sell => best_ask < (ctx.entry_price - Decimal::from(self.params.price_runaway_ticks) * self.params.tick_size),
        };

        let timed_out = (now - ctx.placed_at).num_seconds() > self.params.order_timeout_seconds;

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

        let now = Utc::now();
        // Backoff check
        if let Some(last_action) = ctx.last_action_at {
            if (now - last_action).num_milliseconds() < self.params.retry_backoff_ms {
                return StrategyAction::None;
            }
        }

        let current_wall_v = self.lob.get_volume(ctx.side, ctx.wall_price);
        let threshold = self.analytics.avg_background_vol * self.params.wall_ratio_threshold * self.params.panic_wall_ratio;
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
            let exit_side = if ctx.side == Side::Buy { Side::Sell } else { Side::Buy };
            if let Some(order_id) = &ctx.order_id {
                return StrategyAction::PanicExit {
                    side: exit_side,
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
                    last_action_at: None,
                    last_queried_at: None,
                    order_id: None,
                    filled_qty: Decimal::ZERO,
                    avg_fill_price: None,
                });
            }
            StrategyAction::CancelEntry { .. } => {
                self.state = StrategyState::Cancelling;
            }
            StrategyAction::PanicExit { .. } => {
                self.state = StrategyState::PanicExiting;
            }
            StrategyAction::RequestStatusUpdate { .. } => {
                // Keep current state, just a query
            }
            StrategyAction::None => {}
        }
    }

    pub fn reset(&mut self) {
        self.state = StrategyState::Idle;
        self.ctx = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::StrategyParameters;
    use rust_decimal_macros::dec;

    fn setup_strategy() -> AdaptiveWallStrategyLogic {
        AdaptiveWallStrategyLogic::new(StrategyParameters::default_btcusdt())
    }

    #[test]
    fn test_transit_state_cancelling() {
        let mut strategy = setup_strategy();
        
        // 1. Place order
        let action = StrategyAction::OpenPosition {
            side: Side::Buy,
            wall_price: dec!(50000.0),
            entry_price: dec!(50000.1),
            qty: dec!(0.1),
            stop_loss: dec!(49500.0),
            take_profit: dec!(51000.0),
        };
        strategy.update_state(&action);
        if let Some(ctx) = &mut strategy.ctx {
            ctx.order_id = Some("test_order".to_string());
        }
        assert_eq!(strategy.state, StrategyState::OrderPlaced);

        // 2. Trigger Cancel
        let cancel_action = StrategyAction::CancelEntry {
            order_id: "test_order".to_string(),
            reason: "Test".to_string(),
        };
        strategy.update_state(&cancel_action);
        assert_eq!(strategy.state, StrategyState::Cancelling);

        // 3. Verify that on_tick/on_orderbook return None while in Cancelling
        let tick = Tick {
            timestamp: Utc::now(),
            symbol: "BTCUSDT".to_string(),
            price: dec!(49999.0), // Price broke the wall!
            volume: dec!(1.0),
            side: Some(Side::Sell),
        };
        let action_during_transit = strategy.on_tick(&tick);
        assert!(matches!(action_during_transit, StrategyAction::None));
    }

    #[test]
    fn test_backoff_logic_after_failure() {
        let mut strategy = setup_strategy();
        
        // 1. Setup OrderPlaced with last_action_at (failed attempt just now)
        strategy.state = StrategyState::OrderPlaced;
        strategy.ctx = Some(TradeContext {
            side: Side::Buy,
            wall_price: dec!(50000.0),
            entry_price: dec!(50000.1),
            qty: dec!(0.1),
            stop_loss: dec!(49500.0),
            take_profit: dec!(51000.0),
            placed_at: Utc::now(),
            last_action_at: Some(Utc::now()), // FAILED JUST NOW
            last_queried_at: None,
            order_id: Some("test_order".to_string()),
            filled_qty: Decimal::ZERO,
            avg_fill_price: None,
        });

        // 2. Price breaks wall, strategy should normally cancel, but backoff is active
        let tick = Tick {
            timestamp: Utc::now(),
            symbol: "BTCUSDT".to_string(),
            price: dec!(49999.0),
            volume: dec!(1.0),
            side: Some(Side::Sell),
        };
        
        let action = strategy.on_tick(&tick);
        assert!(matches!(action, StrategyAction::None), "Backoff should prevent repeated cancel action");

        // 3. Simulate time pass (1.1s)
        if let Some(ctx) = &mut strategy.ctx {
            ctx.last_action_at = Some(Utc::now() - chrono::Duration::milliseconds(1100));
        }
        
        let action_after_backoff = strategy.on_tick(&tick);
        assert!(matches!(action_after_backoff, StrategyAction::CancelEntry { .. }), "Action should be allowed after backoff");
    }
}

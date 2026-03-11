use serde::{Deserialize, Serialize};
use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use crate::{Price, Qty, Side, StrategyParameters};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Ohlc {
    pub open: Price,
    pub high: Price,
    pub low: Price,
    pub close: Price,
    pub volume: Qty,
}

pub struct MarketAnalytics {
    pub avg_background_vol: Decimal,
    pub current_tp_pct: Decimal,
    pub is_initialized: bool,
}

impl MarketAnalytics {
    pub fn new() -> Self {
        Self {
            avg_background_vol: dec!(0),
            current_tp_pct: dec!(0.1), // Default 0.1%
            is_initialized: false,
        }
    }

    pub fn update_background_volume(&mut self, current_bg_vol: Decimal, alpha: Decimal) {
        if current_bg_vol <= dec!(0) {
            return;
        }

        if !self.is_initialized {
            self.avg_background_vol = current_bg_vol;
            self.is_initialized = true;
        } else {
            self.avg_background_vol = alpha * current_bg_vol + (dec!(1) - alpha) * self.avg_background_vol;
        }
    }

    pub fn calculate_exits(
        &self,
        side: Side,
        entry_price: Price,
        wall_price: Price,
        params: &StrategyParameters,
    ) -> (Price, Price) {
        let tick = params.tick_size;
        let sl_offset = Decimal::from(params.stop_loss_ticks) * tick;
        
        let (raw_tp, raw_sl) = match side {
            Side::Buy => {
                let tp = entry_price * (dec!(1) + self.current_tp_pct / dec!(100));
                let sl = wall_price - sl_offset;
                (tp, sl)
            }
            Side::Sell => {
                let tp = entry_price * (dec!(1) - self.current_tp_pct / dec!(100));
                let sl = wall_price + sl_offset;
                (tp, sl)
            }
        };

        let tp_price = (raw_tp / tick).round() * tick;
        let sl_price = (raw_sl / tick).round() * tick;

        (tp_price, sl_price)
    }

    pub fn update_natr(&mut self, klines: &[Ohlc], natr_multiplier: Decimal, min_tp: Decimal) {
        if klines.len() < 2 {
            return;
        }

        let mut trs = Vec::new();
        for i in 0..klines.len() - 1 {
            let curr = &klines[i];
            let prev = &klines[i + 1];

            let tr1 = curr.high - curr.low;
            let tr2 = (curr.high - prev.close).abs();
            let tr3 = (curr.low - prev.close).abs();

            let tr = tr1.max(tr2).max(tr3);
            trs.push(tr);
        }

        let sum_tr: Decimal = trs.iter().sum();
        let atr = sum_tr / Decimal::from(trs.len());
        let current_close = klines[0].close;

        if current_close > dec!(0) {
            let natr = (atr / current_close) * dec!(100);
            self.current_tp_pct = (natr * natr_multiplier).max(min_tp);
        }
    }
}

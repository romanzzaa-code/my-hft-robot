use crate::{LocalOrderBook, Price, Side, StrategyParameters};
use rust_decimal::Decimal;

pub struct WallSignal {
    pub side: Side,
    pub wall_price: Price,
    pub entry_price: Price,
}

pub struct WallDetector {
    confirms: u32,
    required_confirms: u32,
}

impl WallDetector {
    pub fn new(required_confirms: u32) -> Self {
        Self {
            confirms: 0,
            required_confirms,
        }
    }

    pub fn detect_signal(
        &mut self,
        lob: &LocalOrderBook,
        avg_vol: Decimal,
        params: &StrategyParameters,
    ) -> Option<WallSignal> {
        let best_bid_p = lob.get_best(Side::Buy)?;
        let best_ask_p = lob.get_best(Side::Sell)?;

        let best_bid_v = lob.get_volume(Side::Buy, best_bid_p);
        let best_ask_v = lob.get_volume(Side::Sell, best_ask_p);

        let threshold = avg_vol * params.wall_ratio_threshold;

        let is_bid_wall = best_bid_v > threshold && (best_bid_v * best_bid_p > params.min_wall_value_usdt);
        let is_ask_wall = best_ask_v > threshold && (best_ask_v * best_ask_p > params.min_wall_value_usdt);

        if is_bid_wall || is_ask_wall {
            self.confirms += 1;
        } else {
            self.confirms = 0;
        }

        if self.confirms >= self.required_confirms {
            self.confirms = 0;
            if is_bid_wall {
                Some(WallSignal {
                    side: Side::Buy,
                    wall_price: best_bid_p,
                    entry_price: best_bid_p + params.tick_size,
                })
            } else if is_ask_wall {
                Some(WallSignal {
                    side: Side::Sell,
                    wall_price: best_ask_p,
                    entry_price: best_ask_p - params.tick_size,
                })
            } else {
                None
            }
        } else {
            None
        }
    }
}

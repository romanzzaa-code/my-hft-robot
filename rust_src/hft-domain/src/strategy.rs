use serde::{Deserialize, Serialize};
use rust_decimal::Decimal;
use chrono::{DateTime, Utc};
use crate::{Side, Price, Qty};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StrategyParameters {
    pub symbol: String,
    pub tick_size: Decimal,
    pub lot_size: Decimal,
    pub min_qty: Qty,
    pub order_amount_usdt: Decimal,
    pub min_wall_value_usdt: Decimal,
    pub wall_ratio_threshold: Decimal, // Насколько стена должна быть больше среднего (напр. 5.0)
    pub vol_ema_alpha: Decimal,
    pub entry_touch_tolerance: bool,    // Игнорировать ли касание стены тиком
    pub exit_wall_tolerance_ticks: i32, // Сколько тиков пробоя стены допускаем перед паникой
    pub stop_loss_ticks: i32,
    pub take_profit_ticks: i32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum StrategyState {
    Idle,
    OrderPlaced,
    InPosition,
    Error,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradeContext {
    pub side: Side,
    pub wall_price: Price,
    pub entry_price: Price,
    pub qty: Qty,
    pub stop_loss: Price,
    pub take_profit: Price,
    pub placed_at: DateTime<Utc>,
    pub order_id: Option<String>,
    pub filled_qty: Qty,
    pub avg_fill_price: Option<Price>,
}

impl StrategyParameters {
    pub fn default_btcusdt() -> Self {
        use rust_decimal_macros::dec;
        Self {
            symbol: "BTCUSDT".to_string(),
            tick_size: dec!(0.1),
            lot_size: dec!(0.0001),
            min_qty: dec!(0.001),
            order_amount_usdt: dec!(100.0),
            min_wall_value_usdt: dec!(100000.0),
            wall_ratio_threshold: dec!(5.0),
            vol_ema_alpha: dec!(0.1),
            entry_touch_tolerance: true,
            exit_wall_tolerance_ticks: 2,
            stop_loss_ticks: 50,
            take_profit_ticks: 100,
        }
    }
}

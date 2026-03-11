pub mod strategy;
pub mod analytics;
pub mod detector;
pub mod orderbook;
pub mod strategy_logic;

pub use strategy::{StrategyParameters, StrategyState, TradeContext};
pub use analytics::{MarketAnalytics, Ohlc};
pub use detector::{WallDetector, WallSignal};
pub use orderbook::LocalOrderBook;
pub use strategy_logic::{AdaptiveWallStrategyLogic, StrategyAction};
use serde::{Deserialize, Serialize};
use rust_decimal::Decimal;
use chrono::{DateTime, Utc};
use strum_macros::Display;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Display)]
pub enum Side {
    #[serde(rename = "Buy")]
    Buy,
    #[serde(rename = "Sell")]
    Sell,
}

#[derive(Debug, thiserror::Error)]
pub enum ExecutionError {
    #[error("Insufficient funds")]
    InsufficientFunds,
    #[error("Rate limited")]
    RateLimited,
    #[error("Order rejected: {0}")]
    OrderRejected(String),
    #[error("Network error: {0}")]
    NetworkError(String),
    #[error("Other error: {0}")]
    Other(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tick {
    pub timestamp: DateTime<Utc>,
    pub symbol: String,
    pub price: Decimal,
    pub volume: Decimal,
    pub side: Option<Side>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderBookLevel {
    pub price: Decimal,
    pub volume: Decimal,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderBook {
    pub timestamp: DateTime<Utc>,
    pub symbol: String,
    pub bids: Vec<OrderBookLevel>,
    pub asks: Vec<OrderBookLevel>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionReport {
    pub order_id: String,
    pub symbol: String,
    pub side: Side,
    pub exec_price: Price,
    pub exec_qty: Qty,
    pub remaining_qty: Qty,
    pub is_fully_filled: bool,
}

#[async_trait::async_trait]
pub trait ExecutionHandler: Send + Sync {
    async fn place_limit_order(
        &self,
        symbol: &str,
        side: Side,
        price: Price,
        qty: Qty,
        stop_loss: Option<Price>,
        take_profit: Option<Price>,
    ) -> Result<String, ExecutionError>;

    async fn cancel_order(&self, symbol: &str, order_id: &str) -> Result<(), ExecutionError>;
    async fn place_market_order(&self, symbol: &str, side: Side, qty: Qty) -> Result<String, ExecutionError>;
    async fn query_order(&self, symbol: &str, order_id: &str) -> Result<ExecutionReport, ExecutionError>;
}

pub type Price = Decimal;
pub type Qty = Decimal;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TickerSnapshot {
    pub symbol: String,
    pub last_price: Price,
    pub turnover_24h: Decimal,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScannedMarket {
    pub symbol: String,
    pub turnover_24h: Decimal,
    pub natr: Decimal,
}

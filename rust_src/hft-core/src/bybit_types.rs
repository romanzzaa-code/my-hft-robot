use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
pub struct BybitTradeData {
    #[serde(rename = "T")]
    pub timestamp: u64,
    #[serde(rename = "s")]
    pub symbol: String,
    #[serde(rename = "S")]
    pub side: String,
    #[serde(rename = "p")]
    pub price: String,
    #[serde(rename = "v")]
    pub volume: String,
}

#[derive(Debug, Deserialize)]
pub struct BybitTradeMessage {
    pub topic: String,
    pub data: Vec<BybitTradeData>,
}

#[derive(Debug, Deserialize)]
pub struct BybitOrderBookData {
    #[serde(rename = "s")]
    pub symbol: String,
    pub b: Vec<Vec<String>>,
    pub a: Vec<Vec<String>>,
}

#[derive(Debug, Deserialize)]
pub struct BybitOrderBookMessage {
    pub topic: String,
    pub data: BybitOrderBookData,
    pub ts: u64,
}

#[derive(Debug, Serialize)]
pub struct CreateOrderRequest {
    pub category: String,
    pub symbol: String,
    pub side: String,
    #[serde(rename = "orderType")]
    pub order_type: String,
    pub qty: String,
    pub price: Option<String>,
    #[serde(rename = "timeInForce")]
    pub time_in_force: String,
    #[serde(rename = "orderLinkId")]
    pub order_link_id: Option<String>,
    #[serde(rename = "takeProfit")]
    pub take_profit: Option<String>,
    #[serde(rename = "stopLoss")]
    pub stop_loss: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct CancelOrderRequest {
    pub category: String,
    pub symbol: String,
    #[serde(rename = "orderId")]
    pub order_id: Option<String>,
    #[serde(rename = "orderLinkId")]
    pub order_link_id: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct BybitResponse<T> {
    #[serde(rename = "retCode")]
    pub ret_code: i32,
    #[serde(rename = "retMsg")]
    pub ret_msg: String,
    pub result: Option<T>,
}

#[derive(Debug, Deserialize)]
pub struct CreateOrderResult {
    #[serde(rename = "orderId")]
    pub order_id: String,
    #[serde(rename = "orderLinkId")]
    pub order_link_id: String,
}

#[derive(Debug, Deserialize)]
pub struct BybitTicker {
    pub symbol: String,
    #[serde(rename = "lastPrice")]
    pub last_price: String,
    #[serde(rename = "turnover24h")]
    pub turnover_24h: String,
}

#[derive(Debug, Deserialize)]
pub struct BybitTickerList {
    pub list: Vec<BybitTicker>,
}

#[derive(Debug, Deserialize)]
pub struct BybitKlineList {
    pub list: Vec<Vec<String>>, // [timestamp, open, high, low, close, volume, turnover]
}

#[derive(Debug, Deserialize)]
pub struct BybitOrderUpdateData {
    pub symbol: String,
    #[serde(rename = "orderId")]
    pub order_id: String,
    #[serde(rename = "orderLinkId")]
    pub order_link_id: String,
    pub side: String,
    #[serde(rename = "orderType")]
    pub order_type: String,
    pub price: String,
    pub qty: String,
    #[serde(rename = "orderStatus")]
    pub order_status: String,
    #[serde(rename = "cumExecQty")]
    pub cum_exec_qty: String,
    #[serde(rename = "avgPrice")]
    pub avg_price: String,
}

#[derive(Debug, Deserialize)]
pub struct BybitOrderUpdateMessage {
    pub topic: String,
    pub data: Vec<BybitOrderUpdateData>,
}

#[derive(Debug, Deserialize)]
pub struct BybitOrderQueryList {
    pub list: Vec<BybitOrderUpdateData>,
}

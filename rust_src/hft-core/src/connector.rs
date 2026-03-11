use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use url::Url;
use tracing::{info, error, warn};
use hft_domain::{Tick, OrderBook};
use tokio::sync::mpsc;

pub enum ExchangeMessage {
    Tick(Tick),
    OrderBook(OrderBook),
}

pub trait MessageParser: Send + Sync {
    fn parse(&self, text: &str) -> Result<Vec<ExchangeMessage>>;
}

pub struct BybitParser;

impl MessageParser for BybitParser {
    fn parse(&self, text: &str) -> Result<Vec<ExchangeMessage>> {
        let mut bytes = text.as_bytes().to_vec();
        let mut results = Vec::new();

        if text.contains("publicTrade") {
            let msg: crate::bybit_types::BybitTradeMessage = simd_json::from_slice(&mut bytes)?;
            for trade in msg.data {
                let side = if trade.side == "Buy" { Some(hft_domain::Side::Buy) } else { Some(hft_domain::Side::Sell) };
                results.push(ExchangeMessage::Tick(Tick {
                    timestamp: chrono::DateTime::from_timestamp_millis(trade.timestamp as i64).unwrap_or_default(),
                    symbol: trade.symbol,
                    price: trade.price.parse()?,
                    volume: trade.volume.parse()?,
                    side,
                }));
            }
        } else if text.contains("orderbook") {
            let msg: crate::bybit_types::BybitOrderBookMessage = simd_json::from_slice(&mut bytes)?;
            let bids = msg.data.b.iter()
                .filter_map(|b| Some(hft_domain::OrderBookLevel {
                    price: b.get(0)?.parse().ok()?,
                    volume: b.get(1)?.parse().ok()?,
                })).collect();
            let asks = msg.data.a.iter()
                .filter_map(|a| Some(hft_domain::OrderBookLevel {
                    price: a.get(0)?.parse().ok()?,
                    volume: a.get(1)?.parse().ok()?,
                })).collect();
            
            results.push(ExchangeMessage::OrderBook(OrderBook {
                timestamp: chrono::DateTime::from_timestamp_millis(msg.ts as i64).unwrap_or_default(),
                symbol: msg.data.symbol,
                bids,
                asks,
            }));
        }
        Ok(results)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rust_decimal_macros::dec;

    #[test]
    fn test_bybit_trade_parsing() {
        let parser = BybitParser;
        let json = r#"{
            "topic": "publicTrade.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304486682,
            "data": [
                {
                    "T": 1672304486682,
                    "s": "BTCUSDT",
                    "S": "Buy",
                    "p": "16578.50",
                    "v": "0.001",
                    "L": "PlusTick",
                    "i": "2dd8175d-3f04-5829-873d-82c567a57a80",
                    "BT": false
                }
            ]
        }"#;
        let res = parser.parse(json).unwrap();
        assert_eq!(res.len(), 1);
        if let ExchangeMessage::Tick(tick) = &res[0] {
            assert_eq!(tick.symbol, "BTCUSDT");
            assert_eq!(tick.price, dec!(16578.50));
            assert_eq!(tick.side, Some(hft_domain::Side::Buy));
        } else {
            panic!("Expected Tick message");
        }
    }

    #[test]
    fn test_bybit_orderbook_parsing() {
        let parser = BybitParser;
        let json = r#"{
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304486682,
            "data": {
                "s": "BTCUSDT",
                "b": [["16578.50", "0.001"]],
                "a": [["16579.00", "0.012"]],
                "u": 123456,
                "seq": 123456
            }
        }"#;
        let res = parser.parse(json).unwrap();
        assert_eq!(res.len(), 1);
        if let ExchangeMessage::OrderBook(ob) = &res[0] {
            assert_eq!(ob.symbol, "BTCUSDT");
            assert_eq!(ob.bids[0].price, dec!(16578.50));
            assert_eq!(ob.asks[0].price, dec!(16579.00));
        } else {
            panic!("Expected OrderBook message");
        }
    }
}

pub struct WsConnector {
    url: String,
    tx: mpsc::Sender<ExchangeMessage>,
    parser: Box<dyn MessageParser>,
}

impl WsConnector {
    pub fn new(url: String, tx: mpsc::Sender<ExchangeMessage>, parser: Box<dyn MessageParser>) -> Self {
        Self { url, tx, parser }
    }

    pub async fn run(&self, subscriptions: Vec<String>) -> Result<()> {
        let (ws_stream, _) = connect_async(Url::parse(&self.url)?).await?;
        info!("Connected to {}", self.url);
        
        let (mut write, mut read) = ws_stream.split();

        // Subscribe
        for sub in subscriptions {
            let sub_msg = serde_json::json!({
                "op": "subscribe",
                "args": [sub]
            });
            write.send(Message::Text(sub_msg.to_string())).await?;
        }

        while let Some(msg) = read.next().await {
            match msg {
                Ok(Message::Text(text)) => {
                    match self.parser.parse(&text) {
                        Ok(messages) => {
                            for m in messages {
                                self.tx.send(m).await?;
                            }
                        }
                        Err(e) => error!("Error parsing message: {}", e),
                    }
                }
                Ok(Message::Binary(_bin)) => {}
                Ok(Message::Ping(_)) => {}
                Ok(Message::Pong(_)) => {}
                Ok(Message::Frame(_)) => {}
                Ok(Message::Close(_)) => {
                    warn!("WebSocket closed");
                    break;
                }
                Err(e) => {
                    error!("WebSocket error: {}", e);
                    break;
                }
            }
        }
        Ok(())
    }
}

use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use url::Url;
use tracing::{info, warn};
use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::time::{SystemTime, UNIX_EPOCH};
use hft_domain::{ExecutionReport, Side};
use hft_core::bybit_types::BybitOrderUpdateMessage;
use tokio::sync::mpsc;
use serde_json;
use simd_json;

type HmacSha256 = Hmac<Sha256>;

pub struct BybitPrivateWs {
    url: String,
    api_key: String,
    api_secret: String,
    tx: mpsc::Sender<ExecutionReport>,
}

impl BybitPrivateWs {
    pub fn new(url: String, api_key: String, api_secret: String, tx: mpsc::Sender<ExecutionReport>) -> Self {
        Self { url, api_key, api_secret, tx }
    }

    fn generate_signature(&self, expires: u128) -> String {
        let mut mac = HmacSha256::new_from_slice(self.api_secret.as_bytes())
            .expect("HMAC can take key of any size");
        let sign_data = format!("GET/realtime{}", expires);
        mac.update(sign_data.as_bytes());
        hex::encode(mac.finalize().into_bytes())
    }

    pub async fn run(&self) -> Result<()> {
        let (ws_stream, _) = connect_async(Url::parse(&self.url)?).await?;
        info!("Connected to Bybit Private WS: {}", self.url);
        
        let (mut write, mut read) = ws_stream.split();

        // Auth
        let expires = SystemTime::now()
            .duration_since(UNIX_EPOCH)?
            .as_millis() + 10000;
        let signature = self.generate_signature(expires);
        
        let auth_msg = serde_json::json!({
            "op": "auth",
            "args": [self.api_key, expires, signature]
        });
        write.send(Message::Text(auth_msg.to_string())).await?;

        // Wait for auth confirmation
        if let Some(msg) = read.next().await {
            let msg = msg?;
            if let Message::Text(text) = msg {
                info!("Auth response: {}", text);
            }
        }

        // Subscribe to order updates
        let sub_msg = serde_json::json!({
            "op": "subscribe",
            "args": ["order"]
        });
        write.send(Message::Text(sub_msg.to_string())).await?;

        while let Some(msg) = read.next().await {
            match msg {
                Ok(Message::Text(text)) => {
                    if text.contains("\"topic\":\"order\"") {
                        let mut bytes = text.as_bytes().to_vec();
                        let update: BybitOrderUpdateMessage = simd_json::from_slice(&mut bytes)?;
                        for data in update.data {
                            let side = if data.side == "Buy" { Side::Buy } else { Side::Sell };
                            let report = ExecutionReport {
                                order_id: data.order_id,
                                symbol: data.symbol,
                                side,
                                exec_price: data.avg_price.parse().unwrap_or_default(),
                                exec_qty: data.cum_exec_qty.parse().unwrap_or_default(),
                                remaining_qty: (data.qty.parse::<rust_decimal::Decimal>().unwrap_or_default() - data.cum_exec_qty.parse::<rust_decimal::Decimal>().unwrap_or_default()),
                                is_fully_filled: data.order_status == "Filled",
                            };
                            self.tx.send(report).await?;
                        }
                    }
                }
                Ok(Message::Ping(_)) => {
                    write.send(Message::Pong(vec![])).await?;
                }
                Ok(Message::Close(_)) => {
                    warn!("Private WebSocket closed");
                    break;
                }
                _ => {}
            }
        }
        Ok(())
    }
}

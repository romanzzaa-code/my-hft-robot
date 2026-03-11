use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use url::Url;
use tracing::{info, warn};
use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::time::{SystemTime, UNIX_EPOCH};
use hft_domain::{ExecutionReport, Side};
use tokio::sync::mpsc;
use serde::Deserialize;
use simd_json;

type HmacSha256 = Hmac<Sha256>;

const AUTH_VALIDITY_WINDOW_MS: u128 = 10000;

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

    pub async fn run(&self) -> Result<()> {
        let mut backoff = std::time::Duration::from_secs(1);
        loop {
            info!("Connecting to Bybit Private WS: {}...", self.url);
            
            let ws_result = connect_async(Url::parse(&self.url)?).await;
            
            match ws_result {
                Ok((ws_stream, _)) => {
                    info!("Connected to Bybit Private WS");
                    backoff = std::time::Duration::from_secs(1);
                    
                    let (mut write, mut read) = ws_stream.split();

                    // --- Authentication ---
                    let expires = SystemTime::now()
                        .duration_since(UNIX_EPOCH)?
                        .as_millis() + AUTH_VALIDITY_WINDOW_MS;
                    
                    let mut mac = HmacSha256::new_from_slice(self.api_secret.as_bytes())
                        .expect("HMAC can take key of any size");
                    let sign_data = format!("GET/realtime{}", expires);
                    mac.update(sign_data.as_bytes());
                    let signature = hex::encode(mac.finalize().into_bytes());

                    let auth_msg = serde_json::json!({
                        "op": "auth",
                        "args": [self.api_key, expires, signature]
                    });

                    if let Err(e) = write.send(Message::Text(auth_msg.to_string())).await {
                        warn!("Auth send error: {}. Triggering reconnect.", e);
                        // continue will take us to the end of loop, which sleeps and retries
                    } else {
                        // --- Subscription ---
                        let sub_msg = serde_json::json!({
                            "op": "subscribe",
                            "args": ["order"]
                        });
                        if let Err(e) = write.send(Message::Text(sub_msg.to_string())).await {
                            warn!("Subscribe send error: {}. Triggering reconnect.", e);
                        } else {
                            // --- Main Message Loop ---
                            while let Some(msg) = read.next().await {
                                match msg {
                                    Ok(Message::Text(text)) => {
                                        if text.contains("\"topic\":\"order\"") {
                                            self.handle_order_update(&text).await;
                                        }
                                    }
                                    Ok(Message::Ping(_)) => {
                                        let _ = write.send(Message::Pong(vec![])).await;
                                    }
                                    Ok(Message::Close(_)) => {
                                        warn!("Private WebSocket closed by server. Reconnecting...");
                                        break; 
                                    }
                                    Err(e) => {
                                        warn!("Private WebSocket stream error: {}. Reconnecting...", e);
                                        break;
                                    }
                                    _ => {}
                                }
                            }
                        }
                    }
                }
                Err(e) => {
                    warn!("Private WS connection failed: {}. Retrying in {:?}", e, backoff);
                }
            }
            
            // Reconnection delay with exponential backoff
            tokio::time::sleep(backoff).await;
            backoff = std::cmp::min(backoff * 2, std::time::Duration::from_secs(60));
        }
    }

    async fn handle_order_update(&self, text: &str) {
        let mut bytes = text.as_bytes().to_vec();
        match simd_json::from_slice::<BybitOrderUpdateMessageWrapper>(&mut bytes) {
            Ok(update) => {
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
                    if let Err(e) = self.tx.send(report).await {
                        warn!("Report channel send error (runner might be down): {}", e);
                    }
                }
            }
            Err(e) => warn!("Error parsing private order update: {}", e),
        }
    }
}

#[derive(Deserialize)]
struct BybitOrderUpdateMessageWrapper {
    data: Vec<BybitOrderUpdateData>,
}

#[derive(Deserialize)]
struct BybitOrderUpdateData {
    pub order_id: String,
    pub symbol: String,
    pub side: String,
    pub avg_price: String,
    pub cum_exec_qty: String,
    pub qty: String,
    pub order_status: String,
}

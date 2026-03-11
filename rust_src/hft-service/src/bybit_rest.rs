use hft_domain::{ExecutionHandler, Price, Qty, Side, TickerSnapshot, Ohlc, ExecutionError, ExecutionReport};
use hft_core::bybit_types::{CreateOrderRequest, CancelOrderRequest, BybitResponse, CreateOrderResult, BybitTickerList, BybitKlineList, BybitOrderQueryList};
use anyhow::Result;
use reqwest::Client;
use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::time::{SystemTime, UNIX_EPOCH};
use async_trait::async_trait;
use serde_json;
use rust_decimal::Decimal;
use std::str::FromStr;

type HmacSha256 = Hmac<Sha256>;

#[derive(Clone)]
pub struct BybitRestClient {
    client: Client,
    api_key: String,
    api_secret: String,
    base_url: String,
    recv_window: String,
    category: String,
}

impl BybitRestClient {
    pub fn new(api_key: String, api_secret: String, is_testnet: bool, category: String) -> Self {
        let base_url = if is_testnet {
            "https://api-testnet.bybit.com".to_string()
        } else {
            "https://api.bybit.com".to_string()
        };
        Self::with_url(api_key, api_secret, base_url, category)
    }

    pub fn with_url(api_key: String, api_secret: String, base_url: String, category: String) -> Self {
        Self {
            client: Client::new(),
            api_key,
            api_secret,
            base_url,
            recv_window: "5000".to_string(),
            category,
        }
    }

    fn generate_signature(&self, timestamp: &str, payload: &str) -> String {
        let mut mac = HmacSha256::new_from_slice(self.api_secret.as_bytes())
            .expect("HMAC can take key of any size");
        let sign_data = format!("{}{}{}{}", timestamp, self.api_key, self.recv_window, payload);
        mac.update(sign_data.as_bytes());
        hex::encode(mac.finalize().into_bytes())
    }

    async fn post<T: serde::Serialize, R: serde::de::DeserializeOwned>(&self, path: &str, body: &T) -> Result<R, ExecutionError> {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|e| ExecutionError::Other(e.to_string()))?
            .as_millis()
            .to_string();
        let payload = serde_json::to_string(body).map_err(|e| ExecutionError::Other(e.to_string()))?;
        let signature = self.generate_signature(&timestamp, &payload);

        let url = format!("{}{}", self.base_url, path);
        let res = self.client.post(&url)
            .header("X-BAPI-API-KEY", &self.api_key)
            .header("X-BAPI-TIMESTAMP", &timestamp)
            .header("X-BAPI-SIGN", &signature)
            .header("X-BAPI-RECV-WINDOW", &self.recv_window)
            .header("Content-Type", "application/json")
            .body(payload)
            .send()
            .await
            .map_err(|e| ExecutionError::NetworkError(e.to_string()))?;

        let response = res.json::<BybitResponse<R>>()
            .await
            .map_err(|e| ExecutionError::Other(e.to_string()))?;

        if response.ret_code != 0 {
            return Err(match response.ret_code {
                10001 | 10002 => ExecutionError::RateLimited,
                110001 | 110003 | 110004 | 110007 => ExecutionError::InsufficientFunds,
                _ => ExecutionError::OrderRejected(response.ret_msg),
            });
        }
        response.result.ok_or_else(|| ExecutionError::Other("Bybit API success but no result".to_string()))
    }

    async fn get<R: serde::de::DeserializeOwned>(&self, path: &str, query: Vec<(&str, &str)>) -> Result<R> {
        let mut url = format!("{}{}", self.base_url, path);
        if !query.is_empty() {
            url.push('?');
            for (i, (k, v)) in query.iter().enumerate() {
                if i > 0 { url.push('&'); }
                url.push_str(&format!("{}={}", k, v));
            }
        }

        let response = self.client.get(&url)
            .send()
            .await?
            .json::<BybitResponse<R>>()
            .await?;

        if response.ret_code != 0 {
            anyhow::bail!("Bybit API error {}: {}", response.ret_code, response.ret_msg);
        }
        response.result.ok_or_else(|| anyhow::anyhow!("Bybit API success but no result"))
    }

    async fn get_private<R: serde::de::DeserializeOwned>(&self, path: &str, query: Vec<(&str, &str)>) -> Result<R, ExecutionError> {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|e| ExecutionError::Other(e.to_string()))?
            .as_millis()
            .to_string();
        
        let mut query_string = String::new();
        for (i, (k, v)) in query.iter().enumerate() {
            if i > 0 { query_string.push('&'); }
            query_string.push_str(&format!("{}={}", k, v));
        }

        let signature = self.generate_signature(&timestamp, &query_string);

        let url = if query_string.is_empty() {
            format!("{}{}", self.base_url, path)
        } else {
            format!("{}{}?{}", self.base_url, path, query_string)
        };

        let res = self.client.get(&url)
            .header("X-BAPI-API-KEY", &self.api_key)
            .header("X-BAPI-TIMESTAMP", &timestamp)
            .header("X-BAPI-SIGN", &signature)
            .header("X-BAPI-RECV-WINDOW", &self.recv_window)
            .send()
            .await
            .map_err(|e| ExecutionError::NetworkError(e.to_string()))?;

        let response = res.json::<BybitResponse<R>>()
            .await
            .map_err(|e| ExecutionError::Other(e.to_string()))?;

        if response.ret_code != 0 {
            return Err(match response.ret_code {
                10001 | 10002 => ExecutionError::RateLimited,
                _ => ExecutionError::Other(format!("Bybit API error {}: {}", response.ret_code, response.ret_msg)),
            });
        }
        response.result.ok_or_else(|| ExecutionError::Other("Bybit API success but no result".to_string()))
    }

    pub async fn get_tickers(&self) -> Result<Vec<TickerSnapshot>> {
        let res: BybitTickerList = self.get("/v5/market/tickers", vec![("category", &self.category)]).await?;
        let snapshots = res.list.into_iter().filter_map(|t| {
            Some(TickerSnapshot {
                symbol: t.symbol,
                last_price: Decimal::from_str(&t.last_price).ok()?,
                turnover_24h: Decimal::from_str(&t.turnover_24h).ok()?,
            })
        }).collect();
        Ok(snapshots)
    }

    pub async fn get_instruments(&self) -> Result<Vec<hft_core::bybit_types::BybitInstrumentInfo>> {
        let res: hft_core::bybit_types::BybitInstrumentList = self.get("/v5/market/instruments-info", vec![("category", &self.category)]).await?;
        Ok(res.list)
    }

    pub async fn get_klines(&self, symbol: &str, interval: &str, limit: i32) -> Result<Vec<Ohlc>> {
        let res: BybitKlineList = self.get("/v5/market/kline", vec![
            ("category", &self.category),
            ("symbol", symbol),
            ("interval", interval),
            ("limit", &limit.to_string()),
        ]).await?;

        let klines = res.list.into_iter().filter_map(|k| {
            if k.len() < 6 { return None; }
            Some(Ohlc {
                open: Decimal::from_str(&k[1]).ok()?,
                high: Decimal::from_str(&k[2]).ok()?,
                low: Decimal::from_str(&k[3]).ok()?,
                close: Decimal::from_str(&k[4]).ok()?,
                volume: Decimal::from_str(&k[5]).ok()?,
            })
        }).collect();
        Ok(klines)
    }
}

#[async_trait]
impl ExecutionHandler for BybitRestClient {
    async fn place_limit_order(
        &self,
        symbol: &str,
        side: Side,
        price: Price,
        qty: Qty,
        stop_loss: Option<Price>,
        take_profit: Option<Price>,
    ) -> Result<String, ExecutionError> {
        let req = CreateOrderRequest {
            category: self.category.clone(),
            symbol: symbol.to_string(),
            side: side.to_string(),
            order_type: "Limit".to_string(),
            qty: qty.to_string(),
            price: Some(price.to_string()),
            time_in_force: "GTC".to_string(),
            order_link_id: None,
            take_profit: take_profit.map(|p| p.to_string()),
            stop_loss: stop_loss.map(|p| p.to_string()),
        };

        let result: CreateOrderResult = self.post("/v5/order/create", &req).await?;
        Ok(result.order_id)
    }

    async fn cancel_order(&self, symbol: &str, order_id: &str) -> Result<(), ExecutionError> {
        let req = CancelOrderRequest {
            category: self.category.clone(),
            symbol: symbol.to_string(),
            order_id: Some(order_id.to_string()),
            order_link_id: None,
        };
        let _: serde_json::Value = self.post("/v5/order/cancel", &req).await?;
        Ok(())
    }

    async fn place_market_order(&self, symbol: &str, side: Side, qty: Qty) -> Result<String, ExecutionError> {
        let req = CreateOrderRequest {
            category: self.category.clone(),
            symbol: symbol.to_string(),
            side: side.to_string(),
            order_type: "Market".to_string(),
            qty: qty.to_string(),
            price: None,
            time_in_force: "GTC".to_string(),
            order_link_id: None,
            take_profit: None,
            stop_loss: None,
        };

        let result: CreateOrderResult = self.post("/v5/order/create", &req).await?;
        Ok(result.order_id)
    }

    async fn query_order(&self, symbol: &str, order_id: &str) -> Result<ExecutionReport, ExecutionError> {
        let res: BybitOrderQueryList = self.get_private("/v5/order/realtime", vec![
            ("category", &self.category),
            ("symbol", symbol),
            ("orderId", order_id),
        ]).await?;

        let order = res.list.first().ok_or_else(|| ExecutionError::Other("Order not found".to_string()))?;
        let side = if order.side == "Buy" { Side::Buy } else { Side::Sell };
        
        Ok(ExecutionReport {
            order_id: order.order_id.clone(),
            symbol: order.symbol.clone(),
            side,
            exec_price: Decimal::from_str(&order.avg_price).unwrap_or_default(),
            exec_qty: Decimal::from_str(&order.cum_exec_qty).unwrap_or_default(),
            remaining_qty: Decimal::from_str(&order.qty).unwrap_or_default() - Decimal::from_str(&order.cum_exec_qty).unwrap_or_default(),
            is_fully_filled: order.order_status == "Filled",
        })
    }
}

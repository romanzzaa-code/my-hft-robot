use hft_domain::{ExecutionHandler, Side, Price, Qty};
use crate::BybitRestClient;
use tracing::{info, warn};
use async_trait::async_trait;

pub struct LiveExecutor {
    client: BybitRestClient,
}

impl LiveExecutor {
    pub fn new(client: BybitRestClient) -> Self {
        Self { client }
    }
}

#[async_trait]
impl ExecutionHandler for LiveExecutor {
    async fn place_limit_order(
        &self,
        symbol: &str,
        side: Side,
        price: Price,
        qty: Qty,
        stop_loss: Option<Price>,
        take_profit: Option<Price>,
    ) -> anyhow::Result<String> {
        self.client.place_limit_order(symbol, side, price, qty, stop_loss, take_profit).await
    }

    async fn cancel_order(&self, symbol: &str, order_id: &str) -> anyhow::Result<()> {
        self.client.cancel_order(symbol, order_id).await
    }

    async fn place_market_order(&self, symbol: &str, side: Side, qty: Qty) -> anyhow::Result<String> {
        self.client.place_market_order(symbol, side, qty).await
    }
}

pub struct ShadowExecutor;

#[async_trait]
impl ExecutionHandler for ShadowExecutor {
    async fn place_limit_order(
        &self,
        symbol: &str,
        side: Side,
        price: Price,
        qty: Qty,
        stop_loss: Option<Price>,
        take_profit: Option<Price>,
    ) -> anyhow::Result<String> {
        info!("SHADOW: [PLACE LIMIT] {} {:?} @ {} Qty={} (SL: {:?}, TP: {:?})", 
            symbol, side, price, qty, stop_loss, take_profit);
        Ok(format!("shadow_order_{}", uuid::Uuid::new_v4()))
    }

    async fn cancel_order(&self, symbol: &str, order_id: &str) -> anyhow::Result<()> {
        info!("SHADOW: [CANCEL ORDER] {} ID={}", symbol, order_id);
        Ok(())
    }

    async fn place_market_order(&self, symbol: &str, side: Side, qty: Qty) -> anyhow::Result<String> {
        warn!("SHADOW: [PLACE MARKET] {} {:?} Qty={}", symbol, side, qty);
        Ok(format!("shadow_market_order_{}", uuid::Uuid::new_v4()))
    }
}

use serde::Deserialize;
use std::fs;
use hft_domain::StrategyParameters;
use rust_decimal::Decimal;
use anyhow::Context;

#[derive(Debug, Deserialize)]
pub struct RawStrategyParams {
    pub target_coins: Vec<String>,
    pub investment_usdt: Decimal,
    pub wall_ratio_threshold: Decimal,
    pub min_wall_value_usdt: Decimal,
    pub vol_ema_alpha: Decimal,
}

pub struct AppConfig {
    pub api_key: String,
    pub api_secret: String,
    pub public_ws_url: String,
    pub private_ws_url: String,
    pub is_testnet: bool,
    pub is_shadow: bool,
    pub category: String,
    pub strategy_params: RawStrategyParams,
}

impl AppConfig {
    pub fn load() -> anyhow::Result<Self> {
        dotenvy::dotenv().ok();

        let api_key = std::env::var("MY_API_KEY").context("MY_API_KEY must be set")?;
        let api_secret = std::env::var("MY_API_SECRET").context("MY_API_SECRET must be set")?;
        
        let is_testnet = std::env::var("BYBIT_IS_TESTNET").unwrap_or_else(|_| "false".to_string()) == "true";
        let is_shadow = std::env::var("BYBIT_IS_SHADOW").unwrap_or_else(|_| "false".to_string()) == "true";
        let category = std::env::var("BYBIT_CATEGORY").unwrap_or_else(|_| "linear".to_string());

        // Defaults for Bybit V5
        let public_ws_url = std::env::var("BYBIT_PUBLIC_WS_URL")
            .unwrap_or_else(|_| if is_testnet { "wss://stream-testnet.bybit.com/v5/public/linear".to_string() } else { "wss://stream.bybit.com/v5/public/linear".to_string() });
        let private_ws_url = std::env::var("BYBIT_PRIVATE_WS_URL")
            .unwrap_or_else(|_| if is_testnet { "wss://stream-testnet.bybit.com/v5/private".to_string() } else { "wss://stream.bybit.com/v5/private".to_string() });

        let params_json = fs::read_to_string("config/strategy_params.json")
            .context("Failed to read config/strategy_params.json")?;
        let strategy_params: RawStrategyParams = serde_json::from_str(&params_json)?;

        Ok(Self {
            api_key,
            api_secret,
            public_ws_url,
            private_ws_url,
            is_testnet,
            is_shadow,
            category,
            strategy_params,
        })
    }

    pub fn get_strategy_params(&self, symbol: &str) -> StrategyParameters {
        let mut p = StrategyParameters::default_btcusdt();
        p.symbol = symbol.to_string();
        p.order_amount_usdt = self.strategy_params.investment_usdt;
        p.wall_ratio_threshold = self.strategy_params.wall_ratio_threshold;
        p.min_wall_value_usdt = self.strategy_params.min_wall_value_usdt;
        p.vol_ema_alpha = self.strategy_params.vol_ema_alpha;
        
        // Symbol specific adjustments (should eventually come from exchange info)
        if symbol.contains("BTC") {
            p.tick_size = rust_decimal_macros::dec!(0.1);
            p.lot_size = rust_decimal_macros::dec!(0.0001);
        } else if symbol.contains("ETH") {
            p.tick_size = rust_decimal_macros::dec!(0.01);
            p.lot_size = rust_decimal_macros::dec!(0.001);
        } else {
            // Default generic small coin
            p.tick_size = rust_decimal_macros::dec!(0.0001);
            p.lot_size = rust_decimal_macros::dec!(1.0);
        }
        
        p
    }
}

use anyhow::Result;
use hft_domain::{ScannedMarket, TickerSnapshot, MarketAnalytics};
use crate::BybitRestClient;
use std::sync::Arc;
use tracing::{info, warn};
use futures_util::stream::{FuturesUnordered, StreamExt};
use rust_decimal_macros::dec;

pub struct MarketScannerService {
    client: Arc<BybitRestClient>,
}

impl MarketScannerService {
    pub fn new(client: Arc<BybitRestClient>) -> Self {
        Self { client }
    }

    pub async fn scan(&self, target_coins: &[String], top_n: usize) -> Result<Vec<ScannedMarket>> {
        info!("🔍 Starting Market Scan for {} coins...", target_coins.len());

        // 1. Get all tickers to filter by turnover
        let all_tickers = self.client.get_tickers().await?;
        let target_set: std::collections::HashSet<_> = target_coins.iter().collect();

        let mut liquid_candidates: Vec<TickerSnapshot> = all_tickers
            .into_iter()
            .filter(|t| target_set.contains(&t.symbol) && t.turnover_24h > dec!(1_000_000))
            .collect();

        // 2. Sort by turnover and take top 20 for NATR analysis (like in old code)
        liquid_candidates.sort_by(|a, b| b.turnover_24h.cmp(&a.turnover_24h));
        let top_candidates = if liquid_candidates.len() > 20 {
            &liquid_candidates[..20]
        } else {
            &liquid_candidates[..]
        };

        if top_candidates.is_empty() {
            warn!("⚠️ No liquid candidates found in target coins.");
            return Ok(vec![]);
        }

        // 3. Analyze volatility (NATR) in parallel
        let mut futures = FuturesUnordered::new();
        for ticker in top_candidates {
            let client = self.client.clone();
            let symbol = ticker.symbol.clone();
            let turnover = ticker.turnover_24h;
            
            futures.push(async move {
                match client.get_klines(&symbol, "5", 20).await {
                    Ok(klines) => {
                        let mut analytics = MarketAnalytics::new();
                        // NATR calculation logic from old code
                        analytics.update_natr(&klines, dec!(1), dec!(0));
                        Some(ScannedMarket {
                            symbol,
                            turnover_24h: turnover,
                            natr: analytics.current_tp_pct, // This holds NATR after update_natr
                        })
                    }
                    Err(e) => {
                        warn!("⚠️ NATR calc failed for {}: {}", symbol, e);
                        None
                    }
                }
            });
        }

        let mut results = Vec::new();
        while let Some(res) = futures.next().await {
            if let Some(market) = res {
                results.push(market);
            }
        }

        // 4. Sort by NATR descending and take top_n
        results.sort_by(|a, b| b.natr.cmp(&a.natr));
        results.truncate(top_n);

        info!("🏆 Selected Top {} Targets:", results.len());
        for (i, m) in results.iter().enumerate() {
            info!("   {}. {} | NATR: {:.2}% | Vol 24h: ${:.1}M", 
                i + 1, m.symbol, m.natr, m.turnover_24h / dec!(1_000_000));
        }

        Ok(results)
    }
}

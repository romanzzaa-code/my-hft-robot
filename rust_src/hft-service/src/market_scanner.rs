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

    pub async fn scan(&self, target_coins: Option<&[String]>, top_n: usize) -> Result<Vec<ScannedMarket>> {
        info!("🔍 Starting Smart Market Scan...");

        // 1. Get all active instruments and filter by CopyTrading
        let instruments = self.client.get_instruments().await?;
        let active_copy_symbols: std::collections::HashSet<String> = instruments
            .into_iter()
            .filter(|i| i.status == "Trading" && i.copy_trading == "Enabled")
            .map(|i| i.symbol)
            .collect();

        info!("📋 Found {} instruments with CopyTrading enabled.", active_copy_symbols.len());

        // 2. Get all tickers to filter by candidates
        let all_tickers = self.client.get_tickers().await?;
        
        let liquid_candidates: Vec<TickerSnapshot> = all_tickers
            .into_iter()
            .filter(|t| {
                // If target_coins provided, must be in that list
                let is_target = match target_coins {
                    Some(list) => list.contains(&t.symbol),
                    None => true,
                };
                // Must have CopyTrading enabled (NO VOLUME FILTER anymore)
                is_target && active_copy_symbols.contains(&t.symbol)
            })
            .collect();

        // 3. Take all candidates for NATR analysis (prioritizing volatility)
        // Note: We might want to limit this to top 50 by turnover just to avoid API rate limits, 
        // but the user requested removing the filter. We'll process all copy-trading enabled coins.
        let top_candidates = &liquid_candidates[..];

        if top_candidates.is_empty() {
            warn!("⚠️ No candidates with CopyTrading found.");
            return Ok(vec![]);
        }

        info!("🧪 Analyzing volatility (NATR) for {} candidates...", top_candidates.len());
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

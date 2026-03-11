mod config;
mod bot;

use tracing::{info, warn, Level};
use tracing_subscriber::FmtSubscriber;
use crate::config::AppConfig;
use hft_service::{BybitRestClient, Runner, LiveExecutor, ShadowExecutor, MarketScannerService, BybitRunnerFactory};
use hft_domain::{ExecutionHandler, StrategyState};
use hft_domain::strategy_logic::AdaptiveWallStrategyLogic;
use clap::Parser;
use std::sync::Arc;
use tokio::sync::RwLock;
use tokio::time::{sleep, Duration};
use std::collections::{HashMap, HashSet};

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// Symbol to trade (e.g. BTCUSDT)
    #[arg(short, long)]
    symbol: Option<String>,

    /// Run as Telegram Bot
    #[arg(short, long)]
    bot: bool,

    /// Only scan market and exit
    #[arg(short, long)]
    scan: bool,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args = Args::parse();

    let subscriber = FmtSubscriber::builder()
        .with_max_level(Level::INFO)
        .finish();

    tracing::subscriber::set_global_default(subscriber)
        .expect("setting default subscriber failed");

    let config = Arc::new(AppConfig::load()?);

    if args.bot {
        info!("Starting My HFT Robot in Telegram Bot mode...");
        if let Ok(token) = std::env::var("TG_COMMANDER_TOKEN") {
            std::env::set_var("TELOXIDE_TOKEN", token);
        } else {
            anyhow::bail!("TG_COMMANDER_TOKEN must be set for bot mode");
        }
        
        bot::run_bot(config).await?;
        return Ok(());
    }

    let rest_client = Arc::new(BybitRestClient::new(
        config.api_key.clone(),
        config.api_secret.clone(),
        config.is_testnet,
        config.category.clone(),
    ));

    if args.scan {
        info!("Starting Market Scanner (Full Market Scan)... ");
        let scanner = MarketScannerService::new(rest_client);
        scanner.scan(None, 5).await?;
        return Ok(());
    }

    info!("Starting My HFT Robot in CLI Multi-Runner mode...");

    // 1.Shared state for Hot Symbols (Scanner Output)
    let hot_symbols = Arc::new(RwLock::new(Vec::<String>::new()));
    let scanner_client = rest_client.clone();
    let hot_symbols_clone = hot_symbols.clone();
    let max_coins = config.strategy_params.max_active_coins;

    // 2. Background Scanner Task (Independent, doesn't block anything)
    tokio::spawn(async move {
        let scanner = MarketScannerService::new(scanner_client);
        loop {
            info!("🔄 Background Market Scan starting...");
            match scanner.scan(None, max_coins * 2).await {
                Ok(results) => {
                    let symbols: Vec<String> = results.into_iter().map(|m| m.symbol).collect();
                    if !symbols.is_empty() {
                        let mut hot = hot_symbols_clone.write().await;
                        *hot = symbols;
                        info!("✅ Hot symbols updated: {:?}", *hot);
                    }
                }
                Err(e) => warn!("❌ Background scanner error: {}", e),
            }
            sleep(Duration::from_secs(300)).await;
        }
    });

    // Initial wait for scanner if no symbol provided
    if args.symbol.is_none() {
        info!("Waiting for initial scan...");
        for _ in 0..30 {
            if !hot_symbols.read().await.is_empty() { break; }
            sleep(Duration::from_secs(1)).await;
        }
    }

    // 3. Orchestration Loop (Runs Runners for Top N coins)
    // Structure to track runners and their strategy state
    struct RunnerInfo {
        handle: tokio::task::JoinHandle<()>,
        strategy_state: Arc<RwLock<StrategyState>>,
    }

    let mut active_runners: HashMap<String, RunnerInfo> = HashMap::new();

    loop {
        let current_hot = hot_symbols.read().await.clone();
        let target_symbols: HashSet<String> = if let Some(ref s) = args.symbol {
            let mut h = HashSet::new();
            h.insert(s.to_uppercase());
            h
        } else {
            current_hot.iter().take(max_coins).cloned().collect()
        };

        // --- SOFT STOP LOGIC ---
        // 1. Identify runners for symbols no longer in TOP
        let obsolete_symbols: Vec<String> = active_runners
            .keys()
            .filter(|s| !target_symbols.contains(*s))
            .cloned()
            .collect();

        for symbol in obsolete_symbols {
            let runner_info = active_runners.get(&symbol).unwrap();
            let state = *runner_info.strategy_state.read().await;
            
            // Only stop if NOT in position (SOFT STOP)
            if state == StrategyState::Idle {
                info!("🛑 SOFT STOP: {} is no longer in TOP and has no active position. Stopping.", symbol);
                runner_info.handle.abort();
                active_runners.remove(&symbol);
            } else {
                info!("⏳ PENDING STOP: {} is no longer in TOP but has active state {:?}. Waiting for Idle...", symbol, state);
            }
        }

        // --- START NEW RUNNERS ---
        // 2. Start new runners if we have capacity and new targets
        if active_runners.len() < max_coins {
            for symbol in target_symbols {
                if !active_runners.contains_key(&symbol) && active_runners.len() < max_coins {
                    info!("🚀 Initializing new runner for {}", symbol);
                    
                    let config = config.clone();
                    let rest_client = rest_client.clone();
                    let symbol_clone = symbol.clone();
                    
                    // Share strategy state with orchestrator for soft-stop checks
                    let shared_state = Arc::new(RwLock::new(StrategyState::Idle));
                    let shared_state_clone = shared_state.clone();

                    let handle = tokio::spawn(async move {
                        let params = config.get_strategy_params(&symbol_clone);
                        let mut strategy = AdaptiveWallStrategyLogic::new(params);
                        
                        let executor: Arc<dyn ExecutionHandler> = if config.is_shadow {
                            Arc::new(ShadowExecutor)
                        } else {
                            Arc::new(LiveExecutor::new((*rest_client).clone()))
                        };

                        let (mut runner, _handles) = BybitRunnerFactory::create(
                            strategy,
                            executor,
                            config.public_ws_url.clone(),
                            config.private_ws_url.clone(),
                            config.api_key.clone(),
                            config.api_secret.clone(),
                            symbol_clone.clone(),
                        );

                        info!("Runner for {} started.", symbol_clone);
                        
                        // Internal loop to proxy state to orchestrator
                        loop {
                            // We need a way to let Runner update the shared_state.
                            // For now, we'll implement a simple wrapper or rely on Runner's internal state.
                            // Since Runner owns strategy, we modify Runner to update shared state.
                            if let Err(e) = runner.run_with_state_sync(shared_state_clone.clone()).await {
                                warn!("Runner for {} exited with error: {}", symbol_clone, e);
                                break;
                            }
                            break; // Runner exited normally
                        }
                    });

                    active_runners.insert(symbol, RunnerInfo {
                        handle,
                        strategy_state: shared_state,
                    });
                }
            }
        }

        sleep(Duration::from_secs(5)).await;
    }
}

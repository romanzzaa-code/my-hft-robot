mod config;
mod bot;

use tracing::{info, warn, Level};
use tracing_subscriber::FmtSubscriber;
use crate::config::AppConfig;
use hft_service::{BybitRestClient, Runner, LiveExecutor, ShadowExecutor, MarketScannerService};
use hft_domain::ExecutionHandler;
use hft_domain::strategy_logic::AdaptiveWallStrategyLogic;
use clap::Parser;
use std::sync::Arc;

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
        info!("Starting Market Scanner...");
        let scanner = MarketScannerService::new(rest_client);
        scanner.scan(&config.strategy_params.target_coins, 5).await?;
        return Ok(());
    }

    info!("Starting My HFT Robot in CLI mode...");

    // Selection logic: CLI Arg > Scanner Result > First from config
    let symbol = if let Some(s) = args.symbol {
        s.to_uppercase()
    } else {
        info!("No symbol provided. Scanning for best opportunities...");
        let scanner = MarketScannerService::new(rest_client.clone());
        let results = scanner.scan(&config.strategy_params.target_coins, 1).await?;
        if let Some(best) = results.get(0) {
            info!("🚀 Auto-selected best target: {}", best.symbol);
            best.symbol.clone()
        } else {
            warn!("Scanner found nothing. Falling back to first coin in config.");
            config.strategy_params.target_coins.get(0).cloned().expect("No target coins in config")
        }
    };

    info!("Initializing strategy for {}", symbol);
    if config.is_shadow {
        warn!("!!! RUNNING IN SHADOW MODE (NO REAL ORDERS) !!!");
    }

    let params = config.get_strategy_params(&symbol);
    let strategy = AdaptiveWallStrategyLogic::new(params);
    
    let executor: Arc<dyn ExecutionHandler> = if config.is_shadow {
        Arc::new(ShadowExecutor)
    } else {
        Arc::new(LiveExecutor::new((*rest_client).clone()))
    };

    let (mut runner, _handles) = hft_service::BybitRunnerFactory::create(
        strategy,
        executor,
        config.public_ws_url.clone(),
        config.private_ws_url.clone(),
        config.api_key.clone(),
        config.api_secret.clone(),
        symbol.clone(),
    );

    info!("Runner initialized. Starting loop...");
    runner.run().await?;

    Ok(())
}

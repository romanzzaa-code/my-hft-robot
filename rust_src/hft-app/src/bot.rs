use teloxide::prelude::*;
use teloxide::utils::command::BotCommands;
use crate::config::AppConfig;
use hft_service::{BybitRestClient, Runner, LiveExecutor, ShadowExecutor, MarketScannerService};
use hft_domain::{ExecutionHandler, AdaptiveWallStrategyLogic};
use tokio::sync::Mutex;
use std::sync::Arc;
use tokio::task::JoinHandle;
use tracing::error;

#[derive(BotCommands, Clone)]
#[command(rename_rule = "lowercase", description = "Robot commands:")]
pub enum Command {
    #[command(description = "start the robot: /start <symbol>")]
    Start(String),
    #[command(description = "stop the robot")]
    Stop,
    #[command(description = "get status")]
    Status,
    #[command(description = "scan market for best opportunities")]
    Scan,
}

pub struct BotState {
    pub runner_handle: Option<JoinHandle<()>>,
    pub current_symbol: Option<String>,
}

pub async fn run_bot(config: Arc<AppConfig>) -> anyhow::Result<()> {
    let bot = Bot::from_env();
    let state = Arc::new(Mutex::new(BotState {
        runner_handle: None,
        current_symbol: None,
    }));

    Command::repl(bot, move |bot, msg, cmd| {
        let state = Arc::clone(&state);
        let config = Arc::clone(&config);
        async move {
            let res = handle_command(bot, msg, cmd, state, config).await;
            if let Err(e) = res {
                error!("Error handling bot command: {:?}", e);
            }
            Ok(())
        }
    })
    .await;

    Ok(())
}

async fn handle_command(
    bot: Bot,
    msg: Message,
    cmd: Command,
    state: Arc<Mutex<BotState>>,
    config: Arc<AppConfig>,
) -> ResponseResult<()> {
    match cmd {
        Command::Start(symbol) => {
            let mut s = state.lock().await;
            if s.runner_handle.is_some() {
                bot.send_message(msg.chat.id, format!("Robot already running for {}", s.current_symbol.as_deref().unwrap_or(""))).await?;
                return Ok(());
            }

            let rest_client = Arc::new(BybitRestClient::new(
                config.api_key.clone(),
                config.api_secret.clone(),
                config.is_testnet,
                config.category.clone(),
            ));

            let symbol = if symbol.is_empty() {
                bot.send_message(msg.chat.id, "No symbol provided. Scanning for best target...").await?;
                let scanner = MarketScannerService::new(rest_client.clone());
                let results = scanner.scan(None, 1).await.unwrap_or_default();
                if let Some(best) = results.get(0) {
                    best.symbol.clone()
                } else {
                    config.strategy_params.target_coins.get(0).cloned().unwrap_or_else(|| "BTCUSDT".to_string())
                }
            } else {
                symbol.to_uppercase()
            };

            let mode_str = if config.is_shadow { " (SHADOW MODE)" } else { "" };
            bot.send_message(msg.chat.id, format!("Starting robot for {}{}...", symbol, mode_str)).await?;

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

            let handle = tokio::spawn(async move {
                if let Err(e) = runner.run().await {
                    error!("Runner error: {:?}", e);
                }
            });

            s.runner_handle = Some(handle);
            s.current_symbol = Some(symbol);
        }
        Command::Stop => {
            let mut s = state.lock().await;
            if let Some(handle) = s.runner_handle.take() {
                handle.abort();
                let symbol = s.current_symbol.take().unwrap_or_default();
                bot.send_message(msg.chat.id, format!("Robot for {} stopped.", symbol)).await?;
            } else {
                bot.send_message(msg.chat.id, "Robot is not running.").await?;
            }
        }
        Command::Status => {
            let s = state.lock().await;
            if let Some(symbol) = &s.current_symbol {
                let mode_str = if config.is_shadow { " (SHADOW)" } else { "" };
                bot.send_message(msg.chat.id, format!("Robot is running for {}{}.", symbol, mode_str)).await?;
            } else {
                bot.send_message(msg.chat.id, "Robot is idle.").await?;
            }
        }
        Command::Scan => {
            bot.send_message(msg.chat.id, "Scanning market...").await?;
            let rest_client = Arc::new(BybitRestClient::new(
                config.api_key.clone(),
                config.api_secret.clone(),
                config.is_testnet,
                config.category.clone(),
            ));
            let scanner = MarketScannerService::new(rest_client);
            match scanner.scan(None, 5).await {
                Ok(results) => {
                    let mut text = "🏆 Top Volatile Targets:\n".to_string();
                    for (i, m) in results.iter().enumerate() {
                        text.push_str(&format!("{}. {} | NATR: {:.2}% | Vol: ${:.1}M\n", 
                            i + 1, m.symbol, m.natr, m.turnover_24h / rust_decimal_macros::dec!(1_000_000)));
                    }
                    bot.send_message(msg.chat.id, text).await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("Scan failed: {}", e)).await?;
                }
            }
        }
    }
    Ok(())
}

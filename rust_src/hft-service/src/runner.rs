use anyhow::Result;
use hft_core::connector::{WsConnector, BybitParser, ExchangeMessage};
use hft_domain::{AdaptiveWallStrategyLogic, StrategyAction, Side, ExecutionHandler};
use crate::BybitPrivateWs;
use tokio::sync::mpsc;
use tracing::{info, error, warn};
use std::sync::Arc;
use tokio::sync::Mutex;

pub struct Runner {
    strategy: Arc<Mutex<AdaptiveWallStrategyLogic>>,
    executor: Arc<dyn ExecutionHandler>,
    public_ws_url: String,
    private_ws_url: String,
    api_key: String,
    api_secret: String,
    symbol: String,
}

impl Runner {
    pub fn new(
        strategy: AdaptiveWallStrategyLogic,
        executor: Arc<dyn ExecutionHandler>,
        public_ws_url: String,
        private_ws_url: String,
        api_key: String,
        api_secret: String,
        symbol: String,
    ) -> Self {
        Self {
            strategy: Arc::new(Mutex::new(strategy)),
            executor,
            public_ws_url,
            private_ws_url,
            api_key,
            api_secret,
            symbol,
        }
    }

    pub async fn run(&self) -> Result<()> {
        let (ws_tx, mut ws_rx) = mpsc::channel(100);
        let (exec_tx, mut exec_rx) = mpsc::channel(10);

        let connector = WsConnector::new(
            self.public_ws_url.clone(),
            ws_tx,
            Box::new(BybitParser),
        );

        let private_ws = BybitPrivateWs::new(
            self.private_ws_url.clone(),
            self.api_key.clone(),
            self.api_secret.clone(),
            exec_tx,
        );

        let symbol = self.symbol.clone();
        let subscriptions = vec![
            format!("publicTrade.{}", symbol),
            format!("orderbook.50.{}", symbol),
        ];

        let strategy = self.strategy.clone();
        let executor = self.executor.clone();

        info!("Starting HFT Runner for {}", symbol);

        tokio::select! {
            res = connector.run(subscriptions) => {
                error!("Public WS stopped: {:?}", res);
            }
            res = private_ws.run() => {
                error!("Private WS stopped: {:?}", res);
            }
            _ = async {
                while let Some(msg) = ws_rx.recv().await {
                    let mut strat = strategy.lock().await;
                    let action = match msg {
                        ExchangeMessage::Tick(tick) => strat.on_tick(&tick),
                        ExchangeMessage::OrderBook(ob) => {
                            let bids: Vec<_> = ob.bids.iter().map(|l| (l.price, l.volume)).collect();
                            let asks: Vec<_> = ob.asks.iter().map(|l| (l.price, l.volume)).collect();
                            strat.on_orderbook(bids, asks, false)
                        }
                    };
                    self.handle_action(&mut strat, action, &executor, &symbol).await;
                }
            } => {}
            _ = async {
                while let Some(report) = exec_rx.recv().await {
                    let mut strat = strategy.lock().await;
                    info!("Execution Report: {:?}", report);
                    if let Some(ctx) = &mut strat.ctx {
                        if ctx.order_id == Some(report.order_id.clone()) {
                            ctx.filled_qty = report.exec_qty;
                            if report.is_fully_filled {
                                info!("Order FULLY FILLED: {}", report.order_id);
                                strat.state = hft_domain::StrategyState::InPosition;
                            }
                        }
                    }
                }
            } => {}
        }

        Ok(())
    }

    async fn handle_action(
        &self,
        strat: &mut AdaptiveWallStrategyLogic,
        action: StrategyAction,
        executor: &Arc<dyn ExecutionHandler>,
        symbol: &str,
    ) {
        match action {
            StrategyAction::OpenPosition { side, entry_price, qty, stop_loss, take_profit, .. } => {
                info!("OPEN POSITION: {:?} @ {} Qty={}", side, entry_price, qty);
                match executor.place_limit_order(symbol, side, entry_price, qty, Some(stop_loss), Some(take_profit)).await {
                    Ok(order_id) => {
                        info!("Order placed: {}", order_id);
                        strat.update_state(&action);
                        if let Some(ctx) = &mut strat.ctx {
                            ctx.order_id = Some(order_id);
                        }
                    }
                    Err(e) => error!("Failed to place order: {}", e),
                }
            }
            StrategyAction::CancelEntry { order_id, reason } => {
                info!("CANCEL ENTRY: {} (Reason: {})", order_id, reason);
                match executor.cancel_order(symbol, &order_id).await {
                    Ok(_) => {
                        info!("Order cancelled: {}", order_id);
                        strat.reset();
                    }
                    Err(e) => error!("Failed to cancel order: {}", e),
                }
            }
            StrategyAction::PanicExit { qty, reason, .. } => {
                warn!("PANIC EXIT: Qty={} (Reason: {})", qty, reason);
                let side = if let Some(ctx) = &strat.ctx {
                    if ctx.side == Side::Buy { Side::Sell } else { Side::Buy }
                } else {
                    return;
                };
                match executor.place_market_order(symbol, side, qty).await {
                    Ok(order_id) => {
                        info!("Panic Market Order placed: {}", order_id);
                        strat.reset();
                    }
                    Err(e) => error!("Failed to place panic market order: {}", e),
                }
            }
            StrategyAction::None => {}
        }
    }
}

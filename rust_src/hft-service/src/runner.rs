use anyhow::Result;
use hft_core::connector::ExchangeMessage;
use hft_domain::{AdaptiveWallStrategyLogic, StrategyAction, ExecutionHandler, ExecutionReport, StrategyState};
use crate::{MarketDataStream, ExecutionReportStream};
use tokio::sync::{mpsc, RwLock};
use tracing::{info, error, warn};
use std::sync::Arc;
use chrono::Utc;

/// Результат асинхронного действия экзекутора
pub enum ActionResult {
    EntryOrderPlaced { order_id: String },
    PanicExitPlaced { order_id: String },
    OrderCancelled { order_id: String },
    OrderReportFetched { report: ExecutionReport },
    ActionFailed { action: StrategyAction, error: String },
}

pub struct Runner<M, R, E> 
where 
    M: MarketDataStream,
    R: ExecutionReportStream,
    E: ExecutionHandler + ?Sized + 'static,
{
    strategy: AdaptiveWallStrategyLogic,
    executor: Arc<E>,
    market_data: M,
    execution_reports: R,
    action_results_rx: mpsc::Receiver<ActionResult>,
    action_results_tx: mpsc::Sender<ActionResult>,
    symbol: String,
}

impl<M, R, E> Runner<M, R, E> 
where 
    M: MarketDataStream,
    R: ExecutionReportStream,
    E: ExecutionHandler + ?Sized + 'static,
{
    pub fn new(
        strategy: AdaptiveWallStrategyLogic,
        executor: Arc<E>,
        market_data: M,
        execution_reports: R,
        action_results_rx: mpsc::Receiver<ActionResult>,
        action_results_tx: mpsc::Sender<ActionResult>,
        symbol: String,
    ) -> Self {
        Self {
            strategy,
            executor,
            market_data,
            execution_reports,
            action_results_rx,
            action_results_tx,
            symbol,
        }
    }
    pub async fn run(&mut self) -> Result<()> {
        self.run_with_state_sync(Arc::new(RwLock::new(StrategyState::Idle))).await
    }

    pub async fn run_with_state_sync(&mut self, shared_state: Arc<RwLock<StrategyState>>) -> Result<()> {
        info!("Starting HFT Runner for {}", self.symbol);
        let symbol = self.symbol.clone();

        loop {
            tokio::select! {
                Some(msg) = self.market_data.next_event() => {
                    let start = std::time::Instant::now();
                    let action = match msg {
                        ExchangeMessage::Tick(tick) => self.strategy.on_tick(&tick),
                        ExchangeMessage::OrderBook(ob) => {
                            self.strategy.on_orderbook(&ob.bids, &ob.asks, false)
                        }
                    };

                    if !matches!(action, StrategyAction::None) {
                        let latency = start.elapsed();
                        info!("Strategy logic latency: {:?}. Decision: {:?}", latency, action);
                        self.strategy.update_state(&action);
                        
                        // Sync state to orchestrator
                        let mut s = shared_state.write().await;
                        *s = self.strategy.state;

                        self.handle_strategy_action(action, &symbol);
                    }
                }
                Some(report) = self.execution_reports.next_report() => {
                    self.handle_execution_report(report);
                    // Sync state after report update
                    let mut s = shared_state.write().await;
                    *s = self.strategy.state;
                }
                Some(res) = self.action_results_rx.recv() => {
                    self.handle_action_result(res);
                    // Sync state after action result
                    let mut s = shared_state.write().await;
                    *s = self.strategy.state;
                }
                else => {
                    warn!("One of the streams closed, shutting down runner");
                    break;
                }
            }
        }
        Ok(())
    }

    fn handle_strategy_action(&self, action: StrategyAction, symbol: &str) {
        let executor = self.executor.clone();
        let tx = self.action_results_tx.clone();
        let symbol = symbol.to_string();
        let action_for_err = action.clone();

        tokio::spawn(async move {
            match action {
                StrategyAction::OpenPosition { side, entry_price, qty, stop_loss, take_profit, .. } => {
                    match executor.place_limit_order(&symbol, side, entry_price, qty, Some(stop_loss), Some(take_profit)).await {
                        Ok(order_id) => {
                            let _ = tx.send(ActionResult::EntryOrderPlaced { order_id }).await;
                        }
                        Err(e) => {
                            let _ = tx.send(ActionResult::ActionFailed { action: action_for_err, error: e.to_string() }).await;
                        }
                    }
                }
                StrategyAction::CancelEntry { ref order_id, .. } => {
                    match executor.cancel_order(&symbol, order_id).await {
                        Ok(_) => {
                            let _ = tx.send(ActionResult::OrderCancelled { order_id: order_id.clone() }).await;
                        }
                        Err(e) => {
                            let _ = tx.send(ActionResult::ActionFailed { action: action_for_err, error: e.to_string() }).await;
                        }
                    }
                }
                StrategyAction::PanicExit { side, qty, order_id: _, .. } => {
                    match executor.place_market_order(&symbol, side, qty).await {
                        Ok(new_order_id) => {
                            let _ = tx.send(ActionResult::PanicExitPlaced { order_id: new_order_id }).await;
                        }
                        Err(e) => {
                            let _ = tx.send(ActionResult::ActionFailed { action: action_for_err, error: e.to_string() }).await;
                        }
                    }
                }
                StrategyAction::RequestStatusUpdate { ref order_id } => {
                    match executor.query_order(&symbol, order_id).await {
                        Ok(report) => {
                            let _ = tx.send(ActionResult::OrderReportFetched { report }).await;
                        }
                        Err(e) => {
                            let _ = tx.send(ActionResult::ActionFailed { action: action_for_err, error: e.to_string() }).await;
                        }
                    }
                }
                StrategyAction::None => {}
            }
        });
    }

    fn handle_action_result(&mut self, res: ActionResult) {
        match res {
            ActionResult::EntryOrderPlaced { order_id } => {
                info!("Entry order successfully PLACED: {}", order_id);
                if let Some(ctx) = &mut self.strategy.ctx {
                    ctx.order_id = Some(order_id);
                    ctx.last_action_at = None; // Reset on success
                }
            }
            ActionResult::PanicExitPlaced { order_id } => {
                let entry_p = self.strategy.ctx.as_ref().map(|c| c.entry_price).unwrap_or_default();
                warn!("🔥 PANIC EXIT order placed: {}. Entry was: {}", order_id, entry_p);
                self.strategy.reset(); 
            }
            ActionResult::OrderCancelled { order_id } => {
                info!("Order successfully CANCELLED: {}", order_id);
                self.strategy.reset();
            }
            ActionResult::OrderReportFetched { report } => {
                info!("Fetched order status for {}: filled={}", report.order_id, report.is_fully_filled);
                self.handle_execution_report(report);
            }
            ActionResult::ActionFailed { action, error } => {
                match action {
                    StrategyAction::OpenPosition { .. } => {
                        error!("OpenPosition FAILED: {}. Rolling back to Idle.", error);
                        self.strategy.reset();
                    }
                    StrategyAction::CancelEntry { order_id, .. } => {
                        error!("CancelEntry FAILED for order {}: {}. Retrying with backoff.", order_id, error);
                        if let Some(ctx) = &mut self.strategy.ctx {
                            ctx.last_action_at = Some(Utc::now());
                        }
                        self.strategy.state = StrategyState::OrderPlaced; // Fallback to operational state
                    }
                    StrategyAction::PanicExit { side, qty, reason, .. } => {
                        error!("PanicExit FAILED ({} {}): {}. Reason: {}. Retrying with backoff.", side, qty, error, reason);
                        if let Some(ctx) = &mut self.strategy.ctx {
                            ctx.last_action_at = Some(Utc::now());
                        }
                        self.strategy.state = StrategyState::InPosition; // Fallback to operational state
                    }
                    StrategyAction::RequestStatusUpdate { order_id } => {
                        warn!("RequestStatusUpdate FAILED for order {}: {}", order_id, error);
                    }
                    StrategyAction::None => {}
                }
            }
        }
    }

    fn handle_execution_report(&mut self, report: ExecutionReport) {
        info!("Execution Report: {:?}", report);
        if let Some(ctx) = &mut self.strategy.ctx {
            if ctx.order_id == Some(report.order_id.clone()) {
                ctx.filled_qty = report.exec_qty;
                if report.is_fully_filled {
                    info!("Order FULLY FILLED: {}", report.order_id);
                    self.strategy.state = StrategyState::InPosition;
                }
            }
        }
    }
}

pub struct RxMarketDataStream {
    rx: mpsc::Receiver<ExchangeMessage>,
}

impl RxMarketDataStream {
    pub fn new(rx: mpsc::Receiver<ExchangeMessage>) -> Self {
        Self { rx }
    }
}

#[async_trait::async_trait]
impl MarketDataStream for RxMarketDataStream {
    async fn next_event(&mut self) -> Option<ExchangeMessage> {
        self.rx.recv().await
    }
}

pub struct RxExecutionReportStream {
    rx: mpsc::Receiver<ExecutionReport>,
}

impl RxExecutionReportStream {
    pub fn new(rx: mpsc::Receiver<ExecutionReport>) -> Self {
        Self { rx }
    }
}

#[async_trait::async_trait]
impl ExecutionReportStream for RxExecutionReportStream {
    async fn next_report(&mut self) -> Option<ExecutionReport> {
        self.rx.recv().await
    }
}

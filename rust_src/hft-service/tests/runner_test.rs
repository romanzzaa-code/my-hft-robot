use hft_domain::{
    AdaptiveWallStrategyLogic, ExecutionHandler, ExecutionReport, Side, 
    StrategyParameters, Price, Qty, ExecutionError,
    OrderBook, OrderBookLevel, Tick
};
use hft_core::ExchangeMessage;
use hft_service::{Runner, MarketDataStream, ExecutionReportStream};
use hft_service::runner::{RxMarketDataStream, RxExecutionReportStream};
use tokio::sync::mpsc;
use std::sync::Arc;
use std::time::Duration;
use chrono::Utc;
use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use async_trait::async_trait;

// --- MOCKS ---

struct FlexibleMockExecutor {
    pub order_results: Arc<tokio::sync::Mutex<mpsc::Receiver<Result<String, ExecutionError>>>>,
    pub call_count: Arc<std::sync::atomic::AtomicUsize>,
}

#[async_trait]
impl ExecutionHandler for FlexibleMockExecutor {
    async fn place_limit_order(&self, _: &str, _: Side, _: Price, _: Qty, _: Option<Price>, _: Option<Price>) -> Result<String, ExecutionError> {
        self.call_count.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let mut rx = self.order_results.lock().await;
        rx.recv().await.unwrap_or(Ok("mock_id".into()))
    }
    async fn cancel_order(&self, _: &str, _: &str) -> Result<(), ExecutionError> { Ok(()) }
    async fn place_market_order(&self, _: &str, _: Side, _: Qty) -> Result<String, ExecutionError> { Ok("panic_id".into()) }
    async fn query_order(&self, _: &str, _: &str) -> Result<ExecutionReport, ExecutionError> {
        Err(ExecutionError::Other("Not implemented in mock".into()))
    }
}

fn create_test_params() -> StrategyParameters {
    StrategyParameters {
        symbol: "BTCUSDT".to_string(),
        tick_size: dec!(0.1),
        lot_size: dec!(0.0001),
        min_qty: dec!(0.001),
        order_amount_usdt: dec!(100.0),
        min_wall_value_usdt: dec!(1000.0), // Уменьшим порог для тестов
        wall_ratio_threshold: dec!(5.0),
        vol_ema_alpha: dec!(0.1),
        entry_touch_tolerance: true,
        exit_wall_tolerance_ticks: 2,
        stop_loss_ticks: 50,
        take_profit_ticks: 100,
        cancel_wall_ratio: dec!(0.4),
        panic_wall_ratio: dec!(0.3),
        price_runaway_ticks: 5,
        order_timeout_seconds: 30,
        retry_backoff_ms: 1000,
    }
}

#[tokio::test]
async fn test_runner_race_condition_prevention() {
    let params = create_test_params();
    let mut strategy = AdaptiveWallStrategyLogic::new(params);
    strategy.analytics.avg_background_vol = dec!(1);

    let (order_res_tx, order_res_rx) = mpsc::channel(10);
    let call_count = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    
    let executor = Arc::new(FlexibleMockExecutor {
        order_results: Arc::new(tokio::sync::Mutex::new(order_res_rx)),
        call_count: call_count.clone(),
    });

    let (md_tx, md_rx) = mpsc::channel(100);
    let (er_tx, er_rx) = mpsc::channel(100);
    let (ar_tx, ar_rx) = mpsc::channel(100);

    let mut runner = Runner::new(
        strategy,
        executor,
        RxMarketDataStream::new(md_rx),
        RxExecutionReportStream::new(er_rx),
        ar_rx,
        ar_tx.clone(),
        "BTCUSDT".to_string(),
    );

    let runner_handle = tokio::spawn(async move {
        let _ = runner.run().await;
    });

    // Посылаем сигнал входа (НУЖНО 3 ПОДТВЕРЖДЕНИЯ)
    for _ in 0..3 {
        let ob = OrderBook {
            timestamp: Utc::now(),
            symbol: "BTCUSDT".to_string(),
            bids: vec![OrderBookLevel { price: dec!(50000), volume: dec!(10) }],
            asks: vec![OrderBookLevel { price: dec!(50100), volume: dec!(1) }],
        };
        md_tx.send(ExchangeMessage::OrderBook(ob)).await.unwrap();
    }

    // Даем больше времени
    tokio::time::sleep(Duration::from_millis(50)).await;
    assert_eq!(call_count.load(std::sync::atomic::Ordering::SeqCst), 1, "Should place only one order after 3 confirms");

    // Шлем тики, которые могли бы вызвать повторный вход
    for i in 0..10 {
        let tick = Tick {
            timestamp: Utc::now(),
            symbol: "BTCUSDT".to_string(),
            price: dec!(50001) + dec!(0.1) * Decimal::from(i),
            volume: dec!(1),
            side: Some(Side::Buy),
        };
        md_tx.send(ExchangeMessage::Tick(tick)).await.unwrap();
    }

    tokio::time::sleep(Duration::from_millis(50)).await;
    assert_eq!(call_count.load(std::sync::atomic::Ordering::SeqCst), 1, "Should NOT spam orders");

    runner_handle.abort();
}

#[tokio::test]
async fn test_runner_full_cycle_success() {
    let params = create_test_params();
    let mut strategy = AdaptiveWallStrategyLogic::new(params);
    strategy.analytics.avg_background_vol = dec!(1);

    let (order_res_tx, order_res_rx) = mpsc::channel(10);
    let call_count = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let executor = Arc::new(FlexibleMockExecutor {
        order_results: Arc::new(tokio::sync::Mutex::new(order_res_rx)),
        call_count: call_count.clone(),
    });

    let (md_tx, md_rx) = mpsc::channel(100);
    let (er_tx, er_rx) = mpsc::channel(100);
    let (ar_tx, ar_rx) = mpsc::channel(100);

    let mut runner = Runner::new(
        strategy,
        executor,
        RxMarketDataStream::new(md_rx),
        RxExecutionReportStream::new(er_rx),
        ar_rx,
        ar_tx.clone(),
        "BTCUSDT".to_string(),
    );

    let runner_handle = tokio::spawn(async move {
        let _ = runner.run().await;
    });

    // 1. Вход (3 подтверждения)
    for _ in 0..3 {
        let ob = OrderBook {
            timestamp: Utc::now(),
            symbol: "BTCUSDT".to_string(),
            bids: vec![OrderBookLevel { price: dec!(50000), volume: dec!(10) }],
            asks: vec![OrderBookLevel { price: dec!(50100), volume: dec!(1) }],
        };
        md_tx.send(ExchangeMessage::OrderBook(ob)).await.unwrap();
    }
    
    // Биржа отвечает успехом
    order_res_tx.send(Ok("order_666".to_string())).await.unwrap();
    tokio::time::sleep(Duration::from_millis(50)).await;

    // 2. Исполнение
    let report = ExecutionReport {
        order_id: "order_666".to_string(),
        symbol: "BTCUSDT".to_string(),
        side: Side::Buy,
        exec_price: dec!(50000),
        exec_qty: dec!(0.002),
        remaining_qty: dec!(0),
        is_fully_filled: true,
    };
    er_tx.send(report).await.unwrap();
    tokio::time::sleep(Duration::from_millis(50)).await;

    // 3. Паника
    let ob_empty = OrderBook {
        timestamp: Utc::now(),
        symbol: "BTCUSDT".to_string(),
        bids: vec![OrderBookLevel { price: dec!(50000), volume: dec!(0) }],
        asks: vec![OrderBookLevel { price: dec!(50100), volume: dec!(1) }],
    };
    md_tx.send(ExchangeMessage::OrderBook(ob_empty)).await.unwrap();
    tokio::time::sleep(Duration::from_millis(50)).await;

    runner_handle.abort();
}

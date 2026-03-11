pub mod bybit_rest;
pub mod bybit_ws_private;
pub mod runner;
pub mod executors;
pub mod market_scanner;
pub mod factories;

pub use bybit_rest::BybitRestClient;
pub use bybit_ws_private::BybitPrivateWs;
pub use runner::Runner;
pub use executors::{LiveExecutor, ShadowExecutor};
pub use market_scanner::MarketScannerService;
pub use factories::BybitRunnerFactory;
use hft_core::connector::ExchangeMessage;
use hft_domain::ExecutionReport;

#[async_trait::async_trait]
pub trait MarketDataStream: Send {
    async fn next_event(&mut self) -> Option<ExchangeMessage>;
}

#[async_trait::async_trait]
pub trait ExecutionReportStream: Send {
    async fn next_report(&mut self) -> Option<ExecutionReport>;
}

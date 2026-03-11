use hft_core::connector::{WsConnector, BybitParser};
use hft_domain::{AdaptiveWallStrategyLogic, ExecutionHandler};
use crate::{Runner, BybitPrivateWs, runner::{RxMarketDataStream, RxExecutionReportStream}};
use tokio::sync::mpsc;
use std::sync::Arc;
use tracing::{error, info, warn};

pub struct BybitRunnerFactory;

impl BybitRunnerFactory {
    pub fn create(
        strategy: AdaptiveWallStrategyLogic,
        executor: Arc<dyn ExecutionHandler>,
        public_ws_url: String,
        private_ws_url: String,
        api_key: String,
        api_secret: String,
        symbol: String,
    ) -> (Runner<RxMarketDataStream, RxExecutionReportStream, dyn ExecutionHandler>, Vec<tokio::task::JoinHandle<()>>) {
        let (ws_tx, ws_rx) = mpsc::channel(100);
        let (exec_tx, exec_rx) = mpsc::channel(10);
        let (action_tx, action_rx) = mpsc::channel(10);

        let subs = vec![
            format!("publicTrade.{}", symbol),
            format!("orderbook.50.{}", symbol),
        ];

        let connector = WsConnector::new(
            public_ws_url,
            ws_tx,
            Box::new(BybitParser),
        );

        let private_ws = BybitPrivateWs::new(
            private_ws_url,
            api_key,
            api_secret,
            exec_tx,
        );

        // Public WS Loop with Reconnect logic
        let h1 = tokio::spawn(async move {
            let mut backoff = std::time::Duration::from_secs(1);
            loop {
                info!("Starting Public WS connector for symbols: {:?}", subs);
                if let Err(e) = connector.run(subs.clone()).await {
                    error!("Public WS error: {:?}. Retrying in {:?}", e, backoff);
                } else {
                    warn!("Public WS connector stopped. Retrying in {:?}", backoff);
                }
                tokio::time::sleep(backoff).await;
                backoff = std::cmp::min(backoff * 2, std::time::Duration::from_secs(60));
            }
        });

        // Private WS Loop with internal reconnect (already implemented in BybitPrivateWs::run)
        let h2 = tokio::spawn(async move {
            if let Err(e) = private_ws.run().await {
                error!("Private WS fatal error: {:?}", e);
            }
        });

        let runner = Runner::new(
            strategy,
            executor,
            RxMarketDataStream::new(ws_rx),
            RxExecutionReportStream::new(exec_rx),
            action_rx,
            action_tx,
            symbol,
        );

        (runner, vec![h1, h2])
    }
}

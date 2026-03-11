use hft_domain::{
    AdaptiveWallStrategyLogic, StrategyParameters, StrategyState, 
    Side, Tick, StrategyAction
};
use rust_decimal_macros::dec;
use chrono::Utc;

#[tokio::test]
async fn test_wall_bounce_scenario() {
    let mut params = StrategyParameters::default_btcusdt();
    params.wall_ratio_threshold = dec!(5);
    params.min_wall_value_usdt = dec!(100000);
    params.order_amount_usdt = dec!(1000);
    params.tick_size = dec!(0.1);
    params.lot_size = dec!(0.001);
    
    let mut strategy = AdaptiveWallStrategyLogic::new(params.clone());
    strategy.analytics.update_background_volume(dec!(1), dec!(1)); 

    let wall_price = dec!(50000);
    let bids = vec![(wall_price, dec!(10))];
    let asks = vec![(dec!(50100), dec!(1))];
    
    let mut action = StrategyAction::None;
    for _ in 0..5 {
        action = strategy.on_orderbook(bids.clone(), asks.clone(), true);
        if matches!(action, StrategyAction::OpenPosition { .. }) { break; }
    }
    
    if let StrategyAction::OpenPosition { .. } = action {
        strategy.update_state(&action);
        if let Some(ctx) = &mut strategy.ctx {
            ctx.order_id = Some("test_order_123".to_string());
        }
    }

    assert_eq!(strategy.state, StrategyState::OrderPlaced);

    // Wall Consumption (20%)
    let bids_consumed = vec![(wall_price, dec!(8))];
    let action = strategy.on_orderbook(bids_consumed, asks.clone(), true);
    assert!(matches!(action, StrategyAction::None));

    // Fill
    if let Some(ctx) = &mut strategy.ctx {
        ctx.filled_qty = dec!(0.02); 
        strategy.state = StrategyState::InPosition;
    }

    // Bounce 5%
    let tick_bounce = Tick {
        timestamp: Utc::now(),
        symbol: "BTCUSDT".to_string(),
        price: dec!(52500),
        volume: dec!(0.1),
        side: Some(Side::Buy),
    };
    let action = strategy.on_tick(&tick_bounce);
    assert!(matches!(action, StrategyAction::None));
    
    println!("✅ Strategy Test Passed: Wall detected, 20% consumed, position held during 5% bounce.");
}

#[tokio::test]
async fn test_wall_collapse_panic_exit() {
    let mut params = StrategyParameters::default_btcusdt();
    params.wall_ratio_threshold = dec!(5);
    params.min_wall_value_usdt = dec!(100000);
    params.order_amount_usdt = dec!(1000);
    params.tick_size = dec!(0.1);
    
    let mut strategy = AdaptiveWallStrategyLogic::new(params.clone());
    strategy.analytics.update_background_volume(dec!(1), dec!(1)); 

    let wall_price = dec!(50000);
    let bids = vec![(wall_price, dec!(10))];
    let asks = vec![(dec!(50100), dec!(1))];
    
    let mut final_action = StrategyAction::None;
    for _ in 0..5 {
        final_action = strategy.on_orderbook(bids.clone(), asks.clone(), true);
        if matches!(final_action, StrategyAction::OpenPosition { .. }) { break; }
    }
    strategy.update_state(&final_action);
    
    // ВАЖНО: Устанавливаем order_id, иначе PanicExit не сработает
    if let Some(ctx) = &mut strategy.ctx {
        ctx.order_id = Some("test_order_456".to_string());
        ctx.filled_qty = dec!(0.02);
    }
    strategy.state = StrategyState::InPosition;

    // Wall Collapsed - Объем 10 -> 0.1 BTC (ниже порога 1.5)
    let bids_collapsed = vec![(wall_price, dec!(0.1))];
    let action = strategy.on_orderbook(bids_collapsed, asks, true);
    
    match action {
        StrategyAction::PanicExit { reason, .. } => {
            assert!(reason.contains("Wall Collapsed"));
            println!("✅ Panic Exit triggered correctly: {}", reason);
        },
        _ => panic!("Expected PanicExit due to wall collapse, got {:?}", action),
    }
}

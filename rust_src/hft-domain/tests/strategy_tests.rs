use hft_domain::{
    AdaptiveWallStrategyLogic, StrategyParameters, Side, Tick, StrategyState, StrategyAction
};
use rust_decimal_macros::dec;
use chrono::Utc;

#[test]
fn test_wall_touch_tolerance() {
    let mut params = StrategyParameters::default_btcusdt();
    params.entry_touch_tolerance = true;
    params.tick_size = dec!(1.0);
    
    let mut strategy = AdaptiveWallStrategyLogic::new(params.clone());
    
    // Setup state: OrderPlaced with Wall at 100.0, Entry at 101.0
    strategy.state = StrategyState::OrderPlaced;
    strategy.ctx = Some(hft_domain::TradeContext {
        side: Side::Buy,
        wall_price: dec!(100.0),
        entry_price: dec!(101.0),
        qty: dec!(1.0),
        stop_loss: dec!(90.0),
        take_profit: dec!(110.0),
        placed_at: Utc::now(),
        last_action_at: None,
        last_queried_at: None,
        order_id: Some("test_order".to_string()),
        filled_qty: dec!(0),
        avg_fill_price: None,
    });

    // Tick at 100.0 (touching the wall)
    let tick_touch = Tick {
        timestamp: Utc::now(),
        symbol: "BTCUSDT".to_string(),
        price: dec!(100.0),
        volume: dec!(1.0),
        side: Some(Side::Sell),
    };

    let action = strategy.on_tick(&tick_touch);
    match action {
        StrategyAction::None => {}, // OK: tolerance is ON
        _ => panic!("Expected None, got {:?}", action),
    }

    // Tick at 99.0 (breaking the wall)
    let tick_break = Tick {
        timestamp: Utc::now(),
        symbol: "BTCUSDT".to_string(),
        price: dec!(99.0),
        volume: dec!(1.0),
        side: Some(Side::Sell),
    };

    let action = strategy.on_tick(&tick_break);
    match action {
        StrategyAction::CancelEntry { reason, .. } => {
            assert!(reason.contains("Tick Break 99.0"));
        },
        _ => panic!("Expected CancelEntry, got {:?}", action),
    }
}

#[test]
fn test_no_tolerance_cancel() {
    let mut params = StrategyParameters::default_btcusdt();
    params.entry_touch_tolerance = false; // Tolerance OFF
    params.tick_size = dec!(1.0);
    
    let mut strategy = AdaptiveWallStrategyLogic::new(params.clone());
    strategy.state = StrategyState::OrderPlaced;
    strategy.ctx = Some(hft_domain::TradeContext {
        side: Side::Buy,
        wall_price: dec!(100.0),
        entry_price: dec!(101.0),
        qty: dec!(1.0),
        stop_loss: dec!(90.0),
        take_profit: dec!(110.0),
        placed_at: Utc::now(),
        last_action_at: None,
        last_queried_at: None,
        order_id: Some("test_order".to_string()),
        filled_qty: dec!(0),
        avg_fill_price: None,
    });

    let tick_touch = Tick {
        timestamp: Utc::now(),
        symbol: "BTCUSDT".to_string(),
        price: dec!(100.0),
        volume: dec!(1.0),
        side: Some(Side::Sell),
    };

    let action = strategy.on_tick(&tick_touch);
    match action {
        StrategyAction::CancelEntry { .. } => {}, // OK: cancel on touch
        _ => panic!("Expected CancelEntry, got {:?}", action),
    }
}

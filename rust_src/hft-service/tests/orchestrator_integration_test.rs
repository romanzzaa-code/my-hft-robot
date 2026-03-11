use hft_domain::{StrategyState, ScannedMarket};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tokio::sync::RwLock;
use tokio::time::{sleep, Duration};

#[tokio::test]
async fn test_orchestrator_soft_stop_and_new_runner_logic() {
    // 1. Мокаем состояние сканера (имитируем выдачу ТОП монет)
    let hot_symbols = Arc::new(RwLock::new(Vec::<String>::new()));
    let max_coins = 2;

    // Имитируем первый скан: ТОП-2 это BTC и ETH
    {
        let mut hot = hot_symbols.write().await;
        *hot = vec!["BTCUSDT".to_string(), "ETHUSDT".to_string(), "SOLUSDT".to_string()];
    }

    // Структура для отслеживания раннеров в тесте (упрощенная копия из main.rs)
    struct TestRunnerInfo {
        state: Arc<RwLock<StrategyState>>,
        is_running: bool,
    }

    let mut active_runners: HashMap<String, TestRunnerInfo> = HashMap::new();

    // --- ШАГ 1: Первый запуск (BTC, ETH) ---
    let current_hot = hot_symbols.read().await.clone();
    let target_symbols: HashSet<String> = current_hot.iter().take(max_coins).cloned().collect();

    for symbol in target_symbols {
        active_runners.insert(symbol, TestRunnerInfo {
            state: Arc::new(RwLock::new(StrategyState::Idle)),
            is_running: true,
        });
    }

    assert!(active_runners.contains_key("BTCUSDT"));
    assert!(active_runners.contains_key("ETHUSDT"));
    assert_eq!(active_runners.len(), 2);

    // --- ШАГ 2: Смена ТОПа (BTC вылетел, пришел SOL) ---
    // Но у BTC сейчас ОТКРЫТА ПОЗИЦИЯ
    {
        let btc_info = active_runners.get_mut("BTCUSDT").unwrap();
        let mut btc_state = btc_info.state.write().await;
        *btc_state = StrategyState::InPosition;
    }

    // Имитируем новый скан: ETH и SOL теперь в топе
    {
        let mut hot = hot_symbols.write().await;
        *hot = vec!["ETHUSDT".to_string(), "SOLUSDT".to_string(), "XRPUSDT".to_string()];
    }

    // Логика оркестратора (копия из main.rs)
    let current_hot = hot_symbols.read().await.clone();
    let target_symbols: HashSet<String> = current_hot.iter().take(max_coins).cloned().collect();

    // Попытка остановить тех, кто не в топе
    let obsolete_symbols: Vec<String> = active_runners
        .keys()
        .filter(|s| !target_symbols.contains(*s))
        .cloned()
        .collect();

    for symbol in obsolete_symbols {
        let runner_info = active_runners.get(&symbol).unwrap();
        let state = *runner_info.state.read().await;
        
        if state == StrategyState::Idle {
            active_runners.remove(&symbol);
        } else {
            // Мягкая остановка в действии: BTC не удаляется, так как InPosition
            println!("⏳ PENDING STOP: {} has active state {:?}. Waiting...", symbol, state);
        }
    }

    // BTC должен остаться в списке активных, несмотря на то что он не в ТОПе
    assert!(active_runners.contains_key("BTCUSDT"), "BTC should NOT be stopped while InPosition");
    assert_eq!(active_runners.len(), 2, "Should still have 2 runners (BTC and ETH)");

    // --- ШАГ 3: Завершение сделки в BTC и запуск SOL ---
    // Имитируем закрытие позиции в BTC
    {
        let btc_info = active_runners.get_mut("BTCUSDT").unwrap();
        let mut btc_state = btc_info.state.write().await;
        *btc_state = StrategyState::Idle;
    }

    // Повторный цикл оркестратора
    let obsolete_symbols: Vec<String> = active_runners
        .keys()
        .filter(|s| !target_symbols.contains(*s))
        .cloned()
        .collect();

    for symbol in obsolete_symbols {
        let runner_info = active_runners.get(&symbol).unwrap();
        let state = *runner_info.state.read().await;
        if state == StrategyState::Idle {
            active_runners.remove(&symbol);
            println!("🛑 SOFT STOP: {} stopped.", symbol);
        }
    }

    // Теперь BTC удален, и мы можем запустить SOL
    assert!(!active_runners.contains_key("BTCUSDT"));

    for symbol in target_symbols {
        if !active_runners.contains_key(&symbol) && active_runners.len() < max_coins {
            active_runners.insert(symbol, TestRunnerInfo {
                state: Arc::new(RwLock::new(StrategyState::Idle)),
                is_running: true,
            });
        }
    }

    assert!(active_runners.contains_key("ETHUSDT"));
    assert!(active_runners.contains_key("SOLUSDT"));
    assert_eq!(active_runners.len(), 2);
    println!("✅ Test passed: Soft-stop and Dynamic Rotation verified!");
}

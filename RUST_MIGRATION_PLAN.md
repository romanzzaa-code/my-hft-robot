# Rust Migration Plan: My HFT Robot (Wall Bounce)

## 🎯 Goal
Полный перенос HFT-робота с C++/Python на Rust с сохранением Clean Architecture, максимальной производительностью и 100% покрытием тестами логики входа/выхода.

## 🏗 Target Architecture (Rust)
- **Crate `hft-core`**: Низкоуровневая работа с сетью (WebSockets), парсинг (simd-json).
- **Crate `hft-domain`**: Бизнес-логика, параметры стратегии, расчеты (EMA, NATR), модели данных.
- **Crate `hft-service`**: Оркестрация (Bybit API, Risk Management).
- **Crate `hft-app`**: Точка входа, Telegram бот, CLI.

---

## 📅 Roadmap (Этапы реализации)

### Phase 0: Foundation (Подготовка) [COMPLETED]
- [x] Инициализация Rust Cargo Workspace.
- [x] Определение базовых типов (Price, Qty, Side, OrderBook, Tick) in `hft-domain`.
- [x] Настройка системы логирования (Tracing) и конфигурации (Config-rs).
- [x] Настройка окружения (Rustup, Cargo).

### Phase 1: High-Performance Core (Замена C++) [COMPLETED]
- [x] Реализация WebSocket клиента на `tokio-tungstenite` для Binance/Bybit.
- [x] Интеграция `simd-json` для ультра-быстрого парсинга тиков и стаканов.
- [x] Механизм каналов (Tokio mpsc/broadcast) для передачи данных в стратегию.

### Phase 2: Domain Logic (Портирование Стратегии) [COMPLETED]
- [x] Реализация `StrategyParameters` и логики `Wall Bounce` (Wall Detection).
- [x] Расчеты: `vol_ema_alpha`, `natr_period`, `dynamic_tp`.
- [x] Реализация стейт-машины ордера (Pending, Active, Filled, Cancelled).

### Phase 3: Exchange Services (Bybit API) [COMPLETED]
- [x] Реализация Bybit V5 REST API (Signatures, Order placement, Position info).
- [x] Реализация Bybit V5 WebSocket Private (Order updates, Position updates).
- [x] Реализация `hft-service` runner для оркестрации стратегии и обмена.

### Phase 4: Infrastructure & UI [COMPLETED]
- [x] Telegram Bot on `teloxide` (commands /start, /stop, /status).
- [x] CLI interface for local управления.
- [x] Dockerization (Multi-stage build).
- [x] Mock Tests for `BybitRestClient`.

### Phase 5: Final Verification & Cutover
- [ ] Shadow Trading (запуск Rust версии в режиме логов без реальных ордеров).
- [ ] Поэтапный переход на Live Trading.

---

## 🛠 Engineering Standards
- **Zero Copy**: Максимальное использование ссылок и эффективных структур данных.
- **Error Handling**: Использование `anyhow` для приложений и `thiserror` для библиотек.
- **Async First**: Весь I/O через `tokio`.
- **Formatting**: Строгое соблюдение `cargo fmt` и `cargo clippy`.
- **Testing**: TDD подход.

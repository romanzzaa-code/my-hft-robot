#include "../../include/parsers/bybit_parser.hpp" 
#include "../../include/entities/ticker_data.hpp" // <--- Не забудь этот инклюд!
#include <iostream>
#include <charconv>
#include <chrono>
#include "../../include/entities/execution_data.hpp"

// Вспомогательная функция (оставь как есть, если она уже была)
static double extract_double(simdjson::ondemand::value val) {
    double res = 0.0;
    if (auto num = val.get_double(); !num.error()) {
        return num.value();
    }
    std::string_view sv;
    if (auto str = val.get_string(); !str.error()) {
        sv = str.value();
        if (sv.empty()) return 0.0;
        // Пытаемся распарсить строку
        std::from_chars(sv.data(), sv.data() + sv.size(), res);
        return res;
    }
    return 0.0;
}

static double extract_from_result(simdjson::simdjson_result<simdjson::ondemand::value> res) {
    if (!res.error()) {
        return extract_double(res.value());
    }
    return 0.0;
}

// Обновленная сигнатура метода parse
ParseResultType BybitParser::parse(
    const std::string& payload, 
    TickData& out_tick, 
    OrderBookSnapshot& out_depth,
    TickerData& out_ticker,
    ExecutionData& out_exec // <--- Новый аргумент
) {
    simdjson::padded_string json_data(payload);
    
    try {
        auto doc = parser_.iterate(json_data);
        auto obj = doc.get_object();
        
        std::string_view topic_sv;
        if (obj["topic"].get_string().get(topic_sv)) {
            return ParseResultType::None;
        }
        
 // --- 1. EXECUTIONS (НОВАЯ ЛОГИКА) ---
        if (topic_sv.find("execution") != std::string_view::npos) {
            simdjson::ondemand::array data_arr;
            if (!obj["data"].get(data_arr)) {
                for (auto exec_val : data_arr) {
                    auto exec_obj = exec_val.get_object();
                    
                    // Извлекаем данные
                    std::string_view sv;
                    if (!exec_obj["symbol"].get_string().get(sv)) out_exec.symbol = std::string(sv);
                    if (!exec_obj["orderId"].get_string().get(sv)) out_exec.order_id = std::string(sv);
                    if (!exec_obj["side"].get_string().get(sv)) out_exec.side = std::string(sv);
                    
                    // Цены и объемы
                    if (auto f = exec_obj["execPrice"]; !f.error()) out_exec.exec_price = extract_double(f.value());
                    if (auto f = exec_obj["execQty"]; !f.error()) out_exec.exec_qty = extract_double(f.value());
                    
                    // Maker/Taker
                    if (auto f = exec_obj["isMaker"]; !f.error()) { 
                        bool val; 
                        if (!f.value().get_bool().get(val)) out_exec.is_maker = val; 
                    }

                    // Время
                    int64_t ts = 0;
                    if (auto f = exec_obj["execTime"]; !f.error()) {
                         // В execution топике timestamp часто строка, но simdjson умеет конвертировать,
                         // если это число. Если строка - используем extract_double и кастуем.
                         // Для надежности:
                         out_exec.timestamp = (long long)extract_double(f.value());
                    }

                    return ParseResultType::Execution; 
                }
            }
            return ParseResultType::None;
        }
        // ==========================================
        // 1. ЛОГИКА ТИКЕРОВ (НОВАЯ)
        // ==========================================
        if (topic_sv.find("tickers") != std::string_view::npos) {
            simdjson::ondemand::object data_obj;
            
            // В Bybit V5 Linear ticker -> data это Object, а не Array
            if (obj["data"].get_object().get(data_obj)) {
                 return ParseResultType::None;
            }

            std::string_view sym;
            if (!data_obj["symbol"].get_string().get(sym)) out_ticker.symbol = std::string(sym);
            
            // Извлекаем ключевые метрики для сканера
            if (auto f = data_obj["lastPrice"]; !f.error()) out_ticker.last_price = extract_double(f.value());
            if (auto f = data_obj["turnover24h"]; !f.error()) out_ticker.turnover_24h = extract_double(f.value());
            if (auto f = data_obj["price24hPcnt"]; !f.error()) out_ticker.price_24h_pcnt = extract_double(f.value());

            // Timestamp события
            int64_t ts = 0;
            if (auto f = obj["ts"]; !f.error()) f.get_int64().get(ts);
            out_ticker.timestamp = ts;

            return ParseResultType::Ticker;
        }

        // ==========================================
        // 2. ЛОГИКА СДЕЛОК (Как было)
        // ==========================================
        else if (topic_sv.find("publicTrade") != std::string_view::npos) {
            simdjson::ondemand::array data_arr;
            if (!obj["data"].get(data_arr)) {
                for (auto trade_val : data_arr) {
                    auto trade_obj = trade_val.get_object();
                    double price = 0.0; double vol = 0.0; int64_t ts = 0; std::string symbol_str;
                    
                    if (auto f = trade_obj["p"]; !f.error()) price = extract_double(f.value());
                    if (auto f = trade_obj["v"]; !f.error()) vol = extract_double(f.value());
                    if (auto f = trade_obj["s"]; !f.error()) { std::string_view sv; f.value().get_string().get(sv); symbol_str = std::string(sv); }
                    if (auto f = trade_obj["T"]; !f.error()) { int64_t val; if (!f.value().get_int64().get(val)) ts = val; }

                    if (price > 0) {
                        out_tick = {symbol_str, price, vol, ts};
                        return ParseResultType::Trade; 
                    }
                }
            }
        }
        
        // ==========================================
        // 3. ЛОГИКА СТАКАНА (Как было)
        // ==========================================
        else if (topic_sv.find("orderbook") != std::string_view::npos) {
            std::string_view type_sv;
            if (obj["type"].get_string().get(type_sv)) return ParseResultType::None;

            bool is_snapshot = (type_sv == "snapshot");
            bool is_delta = (type_sv == "delta");

            if (is_snapshot || is_delta) {
                simdjson::ondemand::object data_obj;
                if (obj["data"].get_object().get(data_obj)) return ParseResultType::None;
                
                std::string_view sym;
                if (!data_obj["s"].get_string().get(sym)) out_depth.symbol = std::string(sym);

                int64_t ts = 0;
                if (auto f = obj["ts"]; !f.error()) f.get_int64().get(ts);
                out_depth.timestamp = ts;

                auto now = std::chrono::system_clock::now();
                out_depth.local_timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
                
                out_depth.is_snapshot = is_snapshot;
                out_depth.bids.clear();
                out_depth.asks.clear();
                
                auto parse_levels = [](simdjson::ondemand::object& d_obj, const char* key, std::vector<PriceLevel>& target) {
                    simdjson::ondemand::array levels_arr;
                    if (!d_obj[key].get(levels_arr)) {
                        for (auto level : levels_arr) {
                            simdjson::ondemand::array pair_arr;
                            if (!level.get_array().get(pair_arr)) {
                                auto it = pair_arr.begin();
                                if (it == pair_arr.end()) continue;
                                double p = extract_from_result(*it); 
                                ++it;
                                if (it == pair_arr.end()) continue;
                                double q = extract_from_result(*it);
                                target.push_back({p, q});
                            }
                        }
                    }
                };

                parse_levels(data_obj, "b", out_depth.bids);
                parse_levels(data_obj, "a", out_depth.asks);

                return ParseResultType::Depth;
            }
        }

    } catch (...) { }
    return ParseResultType::None;
}
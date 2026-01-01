#include "../../include/parsers/binance_parser.hpp"
#include "../../include/entities/ticker_data.hpp"
#include "../../include/entities/execution_data.hpp"
#include <iostream>
#include <charconv>
#include <cstdlib> // <--- Добавлено для std::strtod

// Вспомогательная функция с фиксом для Mac M1/M2/M3
static double extract_double(simdjson::ondemand::value val) {
    // 1. Быстрый путь
    if (auto num = val.get_double(); !num.error()) {
        return num.value();
    }
    
    // 2. Медленный путь (строка -> число)
    std::string_view sv;
    if (auto str = val.get_string(); !str.error()) {
        sv = str.value();
        if (sv.empty()) return 0.0;
        
        // FIX: Использование strtod вместо from_chars
        std::string s(sv);
        char* end;
        double res = std::strtod(s.c_str(), &end);
        return res;
    }
    return 0.0;
}

ParseResultType BinanceParser::parse(
    const std::string& payload, 
    TickData& out_tick, 
    OrderBookSnapshot& out_depth,
    TickerData& out_ticker,
    ExecutionData& out_exec 
) {
    simdjson::padded_string json_data(payload);
    
    try {
        auto doc = parser_instance.iterate(json_data);
        auto obj = doc.get_object();
        
        double price = 0.0;
        double vol = 0.0;
        long long ts = 0;
        std::string symbol_str;

        if (auto f = obj["p"]; !f.error()) price = extract_double(f.value());
        if (auto f = obj["q"]; !f.error()) vol = extract_double(f.value());
        
        if (auto f = obj["s"]; !f.error()) {
            std::string_view sv;
            if (!f.value().get_string().get(sv)) symbol_str = std::string(sv);
        }
        
        if (auto f = obj["T"]; !f.error()) { 
             int64_t val; 
             if (!f.value().get_int64().get(val)) ts = val;
        }

        if (price > 0) {
            out_tick = {symbol_str, price, vol, ts};
            return ParseResultType::Trade;
        }

    } catch (...) {
        // Игнорируем ошибки парсинга
    }
    
    return ParseResultType::None;
}
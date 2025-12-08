#include "../../include/parsers/binance_parser.hpp" // Путь может отличаться, проверь
#include <simdjson.h>
#include <iostream>
#include <charconv>

// Вспомогательная функция (можно сделать private static методом)
static double extract_double(simdjson::ondemand::value val) {
    double res = 0.0;
    if (auto num = val.get_double(); !num.error()) {
        return num.value();
    }
    std::string_view sv;
    if (auto str = val.get_string(); !str.error()) {
        sv = str.value();
        if (sv.empty()) return 0.0;
        std::from_chars(sv.data(), sv.data() + sv.size(), res);
        return res;
    }
    return 0.0;
}

bool BinanceParser::parse(const std::string& payload, TickData& out_tick) {
    // ВАЖНО: simdjson требует padding! Создаем его здесь.
    simdjson::padded_string json_data(payload);
    
    try {
        auto doc = parser_instance.iterate(json_data);
        auto obj = doc.get_object();
        
        // Логика Binance: прямой доступ к полям (плоский JSON)
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
        if (auto f = obj["T"]; !f.error()) { // Binance trade time
             int64_t val; if (!f.value().get_int64().get(val)) ts = val;
        }

        if (price > 0) {
            out_tick = {symbol_str, price, vol, ts};
            return true; // Нашли тик!
        }
    } catch (...) {
        // Ошибки парсинга JSON игнорируем или логируем
    }
    return false;
}
#include "../../include/parsers/bybit_parser.hpp" 
#include <iostream>
#include <charconv>

// ... (функция extract_double без изменений) ...
static double extract_double(simdjson::ondemand::value val) {
    // ... (код extract_double тот же, что я давал раньше) ...
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

bool BybitParser::parse(const std::string& payload, TickData& out_tick) {
    // Создаем padding для simdjson
    simdjson::padded_string json_data(payload);
    
    try {
        // ИСПОЛЬЗУЕМ parser_, который объявили в .hpp
        auto doc = parser_.iterate(json_data);
        auto obj = doc.get_object();
        
        simdjson::ondemand::array data_arr;
        if (auto err = obj["data"].get(data_arr); !err) {
            for (auto trade_val : data_arr) {
                auto trade_obj = trade_val.get_object();
                
                double price = 0.0;
                double vol = 0.0;
                long long ts = 0;
                std::string symbol_str;

                if (auto f = trade_obj["p"]; !f.error()) price = extract_double(f.value());
                if (auto f = trade_obj["v"]; !f.error()) vol = extract_double(f.value());
                if (auto f = trade_obj["s"]; !f.error()) {
                    std::string_view sv;
                    if (!f.value().get_string().get(sv)) symbol_str = std::string(sv);
                }
                
                // Исправленный поиск времени (T или t)
                if (auto f = trade_obj["T"]; !f.error()) { 
                     int64_t val; if (!f.value().get_int64().get(val)) ts = val;
                } else if (auto f = trade_obj["t"]; !f.error()) { 
                     int64_t val; if (!f.value().get_int64().get(val)) ts = val;
                }

                if (price > 0) {
                    out_tick = {symbol_str, price, vol, ts};
                    return true; 
                }
            }
        }
    } catch (...) {
        // Игнорируем ошибки парсинга
    }
    return false;
}
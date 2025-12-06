#include "exchange_streamer.hpp"
#include <iostream>
#include <simdjson.h>
#include <charconv> 

static simdjson::ondemand::parser parser;

// --- [HELPER] Универсальный конвертер (Строка/Число -> Double) ---
double extract_double(simdjson::ondemand::value val) {
    // 1. Если это число JSON
    double res = 0.0;
    if (auto num = val.get_double(); !num.error()) {
        return num.value();
    }
    
    // 2. Если это строка JSON (как у Bybit/Binance)
    std::string_view sv;
    if (auto str = val.get_string(); !str.error()) {
        sv = str.value();
        if (sv.empty()) return 0.0;
        // Быстрая конвертация
        std::from_chars(sv.data(), sv.data() + sv.size(), res);
        return res;
    }
    return 0.0;
}

ExchangeStreamer::ExchangeStreamer() {
    ix::initNetSystem();
}

ExchangeStreamer::~ExchangeStreamer() {
    stop();
    ix::uninitNetSystem();
}

void ExchangeStreamer::set_callback(std::function<void(const TickData&)> cb) {
    callback = cb;
}

void ExchangeStreamer::connect(std::string url) {
    webSocket.setUrl(url);
    webSocket.setPingInterval(45);

    webSocket.setOnMessageCallback([this](const ix::WebSocketMessagePtr& msg) {
        if (msg->type == ix::WebSocketMessageType::Message) {
            
            // 1. Padding (Обязательно!)
            simdjson::padded_string json_data(msg->str);

            try {
                auto doc = parser.iterate(json_data);
                auto obj = doc.get_object();

                // Внутренняя лямбда для парсинга одного тика
                auto parse_and_send = [&](simdjson::ondemand::object& trade_obj) {
                    double price = 0.0;
                    double vol = 0.0;
                    long long ts = 0;
                    std::string symbol_str = "";

                    // Цена (p - все биржи)
                    if (auto f = trade_obj["p"]; !f.error()) price = extract_double(f.value());
                    else if (auto f = trade_obj["price"]; !f.error()) price = extract_double(f.value());

                    // Объем (q - Binance, v - Bybit)
                    if (auto f = trade_obj["q"]; !f.error()) vol = extract_double(f.value());
                    else if (auto f = trade_obj["v"]; !f.error()) vol = extract_double(f.value());

                    // Символ (s - все биржи)
                    if (auto f = trade_obj["s"]; !f.error()) {
                        std::string_view sv;
                        if (!f.value().get_string().get(sv)) symbol_str = std::string(sv);
                    }

                    // Время (T - Binance, ts - Bybit внутри data, t - Bybit trade time)
                    if (auto f = trade_obj["T"]; !f.error()) { // Binance
                         int64_t val; if (!f.value().get_int64().get(val)) ts = val;
                    } else if (auto f = trade_obj["t"]; !f.error()) { // Bybit trade time
                         int64_t val; if (!f.value().get_int64().get(val)) ts = val;
                    }

                    // Если нашли цену и есть подписчик -> отправляем
                    if (price > 0 && callback) {
                        if (symbol_str.empty()) symbol_str = "UNKNOWN";
                        TickData tick{symbol_str, price, vol, ts};
                        callback(tick);
                    }
                };

                // --- ЛОГИКА МАРШРУТИЗАЦИИ (Binance vs Bybit) ---
                
                simdjson::ondemand::array data_arr;
                // Проверяем: есть ли поле "data" и является ли оно массивом? (Bybit style)
                if (auto err = obj["data"].get(data_arr); !err) {
                    // Это Bybit! Бежим по массиву сделок
                    for (auto trade_val : data_arr) {
                        simdjson::ondemand::object trade_obj;
                        if (!trade_val.get_object().get(trade_obj)) {
                            parse_and_send(trade_obj);
                        }
                    }
                } 
                else {
                    // [ИСПРАВЛЕНИЕ ТУТ]
                    // Это Binance (плоский JSON). 
                    // Перезапускаем парсер, так как предыдущий поиск "data" мог сдвинуть курсор.
                    auto doc2 = parser.iterate(json_data);
                    
                    simdjson::ondemand::object obj2;
                    // Распаковываем результат get_object(). Если успешно (код 0) -> передаем в функцию
                    if (!doc2.get_object().get(obj2)) {
                        parse_and_send(obj2);
                    }
                }

            } catch (simdjson::simdjson_error&) {
                // Игнорируем ошибки парсинга
            }
        }
        else if (msg->type == ix::WebSocketMessageType::Open) {
            std::cout << "[CPP] Connected!" << std::endl;
        }
    });
}

void ExchangeStreamer::send_message(std::string msg) {
    webSocket.send(msg);
}

void ExchangeStreamer::start() {
    webSocket.start();
}

void ExchangeStreamer::stop() {
    webSocket.stop();
}
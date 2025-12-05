#include "exchange_streamer.hpp"
#include <App.h>
#include <simdjson.h>
#include <iostream>
#include <thread>
#include <vector>

// 1. Структура данных сокета (определяем только здесь, если её нет в hpp)
// Если компилятор снова скажет "redefinition", значит удали это определение отсюда.
struct PerSocketData {
    /* Данные сессии */
};

// Глобальный парсер (потокобезопасен только если каждый поток имеет свой экземпляр, 
// но пока у нас один поток обработки, это ок)
simdjson::ondemand::parser parser;

ExchangeStreamer::ExchangeStreamer() : running(false) {
}

ExchangeStreamer::~ExchangeStreamer() {
    if (running && app_thread.joinable()) {
        app_thread.detach();
    }
}

void ExchangeStreamer::connect(std::string url) {
    urls.push_back(url);
}

void ExchangeStreamer::start() {
    if (running) {
        return;
    }
    
    running = true;
    
    app_thread = std::thread([this]() {
        // Запуск цикла событий uWebSockets
        auto app = uWS::App();
        
        for (const auto& url : urls) {
            
            // Настройка поведения WebSocket
            // Внимание: uWebSockets очень чувствителен к типам.
            uWS::App::WebSocketBehavior<PerSocketData> behavior;
            
            behavior.maxPayloadLength = 16 * 1024;
            behavior.idleTimeout = 60;
            behavior.maxBackpressure = 1 * 1024 * 1024;
            behavior.compression = uWS::DISABLED; // Явно отключаем сжатие

            behavior.open = [](auto *ws) {
                std::cout << "Connected to WebSocket!" << std::endl;
            };

            behavior.message = [](auto *ws, std::string_view message, uWS::OpCode opCode) {
                // ВНИМАНИЕ: Simdjson требует буфер с отступом (padding).
                // Мы должны скопировать данные, так как message от uWS может быть read-only или без паддинга.
                simdjson::padded_string padded_message(message.data(), message.size());
                
                try {
                    // В версии 3.x метод называется iterate(), а не parse()
                    auto doc = parser.iterate(padded_message);
                    
                    double price = 0.0;
                    double volume = 0.0;

                    // Парсинг "на лету" (On-Demand)
                    // Пытаемся найти цену (p или price)
                    auto obj = doc.get_object();
                    
                    // Простой способ поиска без сложных if-ов (для демо)
                    // В реальном HFT мы бы делали это еще быстрее, зная формат биржи.
                    for (auto field : obj) {
                        std::string_view key = field.unescaped_key();
                        if (key == "p" || key == "price") {
                             // В HFT цене могут приходить как string, так и number.
                             // Simdjson умеет парсить строку в double автоматом.
                             auto res = field.value().get_double();
                             if (!res.error()) price = res.value();
                             else {
                                 // Если пришла строка "123.45"
                                 std::string_view p_str;
                                 if (!field.value().get_string().get(p_str)) {
                                     // Конвертация строки в double (можно использовать fast_float)
                                     // Для простоты пока пропустим
                                 }
                             }
                        }
                        else if (key == "q" || key == "quantity") {
                             auto res = field.value().get_double();
                             if (!res.error()) volume = res.value();
                        }
                    }
                    
                    if (price > 0) {
                        std::cout << "TICK: P=" << price << " V=" << volume << std::endl;
                    }

                } catch (const simdjson::simdjson_error &error) {
                    // Ошибки парсинга игнорируем, чтобы не спамить в консоль
                }
            };

            behavior.close = [](auto *ws, int code, std::string_view message) {
                std::cout << "Connection closed" << std::endl;
            };

            // Регистрируем маршрут
            app.ws<PerSocketData>(url, std::move(behavior));
        }
        
        // Запускаем цикл
        app.run(); 
    });
}
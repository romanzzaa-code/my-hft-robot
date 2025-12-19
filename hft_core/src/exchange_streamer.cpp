#include "exchange_streamer.hpp"
#include <iostream>
#include <ixwebsocket/IXNetSystem.h>

// ... конструктор и деструктор без изменений ...
ExchangeStreamer::ExchangeStreamer(std::shared_ptr<IMessageParser> p) 
    : parser(p) 
{
    ix::initNetSystem();
}

ExchangeStreamer::~ExchangeStreamer() {
    stop();
    ix::uninitNetSystem();
}

// ... старые сеттеры ...
void ExchangeStreamer::set_execution_callback(std::function<void(const ExecutionData&)> cb) {
    execution_callback = cb;
}

void ExchangeStreamer::set_tick_callback(std::function<void(const TickData&)> cb) {
    tick_callback = cb;
}

void ExchangeStreamer::set_depth_callback(std::function<void(const OrderBookSnapshot&)> cb) {
    depth_callback = cb;
}

// [NEW] Сеттер для тикеров
void ExchangeStreamer::set_ticker_callback(std::function<void(const TickerData&)> cb) {
    ticker_callback = cb;
}

void ExchangeStreamer::connect(std::string url) {
    webSocket.setUrl(url);
    webSocket.setPingInterval(45);

    webSocket.setOnMessageCallback([this](const ix::WebSocketMessagePtr& msg) {
        if (msg->type == ix::WebSocketMessageType::Message) {
            
            // Создаем буферы для всех типов данных
            TickData temp_tick;
            OrderBookSnapshot temp_depth;
            TickerData temp_ticker;
            ExecutionData temp_exec;
            
            if (parser) {
                // Передаем все четыре буфера в парсер
                ParseResultType result = parser->parse(msg->str, temp_tick, temp_depth, temp_ticker, temp_exec);
                
                // Маршрутизация на основе результата
                if (result == ParseResultType::Trade) {
                    if (tick_callback) tick_callback(temp_tick);
                } 
                else if (result == ParseResultType::Depth) {
                    if (depth_callback) depth_callback(temp_depth);
                }
                else if (result == ParseResultType::Ticker) { // <--- Новая ветка
                    if (ticker_callback) ticker_callback(temp_ticker);
                }
                else if (result == ParseResultType::Execution) { // <--- Новая ветка
                    if (execution_callback) execution_callback(temp_exec);
                }
            }
        }
        else if (msg->type == ix::WebSocketMessageType::Open) {
            std::cout << "[CPP] Connected!" << std::endl;
        }
    });
}

// ... остальное (send_message, start, stop) без изменений ...
void ExchangeStreamer::send_message(std::string msg) { webSocket.send(msg); }
void ExchangeStreamer::start() { webSocket.start(); }
void ExchangeStreamer::stop() { webSocket.stop(); }
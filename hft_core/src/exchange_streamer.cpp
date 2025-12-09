// hft_core/src/exchange_streamer.cpp
#include "exchange_streamer.hpp"
#include <iostream>
#include <ixwebsocket/IXNetSystem.h>

ExchangeStreamer::ExchangeStreamer(std::shared_ptr<IMessageParser> p) 
    : parser(p) 
{
    ix::initNetSystem();
}

ExchangeStreamer::~ExchangeStreamer() {
    stop();
    ix::uninitNetSystem();
}

void ExchangeStreamer::set_tick_callback(std::function<void(const TickData&)> cb) {
    tick_callback = cb;
}

void ExchangeStreamer::set_depth_callback(std::function<void(const OrderBookSnapshot&)> cb) {
    depth_callback = cb;
}

void ExchangeStreamer::connect(std::string url) {
    webSocket.setUrl(url);
    webSocket.setPingInterval(45);

    webSocket.setOnMessageCallback([this](const ix::WebSocketMessagePtr& msg) {
        if (msg->type == ix::WebSocketMessageType::Message) {
            
            // Буферы для результатов
            TickData temp_tick;
            OrderBookSnapshot temp_depth;
            
            if (parser) {
                // Вызываем универсальный парсинг
                ParseResultType result = parser->parse(msg->str, temp_tick, temp_depth);
                
                // Маршрутизация
                if (result == ParseResultType::Trade) {
                    if (tick_callback) tick_callback(temp_tick);
                } 
                else if (result == ParseResultType::Depth) {
                    if (depth_callback) depth_callback(temp_depth);
                }
            }
        }
        else if (msg->type == ix::WebSocketMessageType::Open) {
            std::cout << "[CPP] Connected!" << std::endl;
        }
    });
}

// ... send_message, start, stop без изменений (как в твоем старом коде) ...
void ExchangeStreamer::send_message(std::string msg) { webSocket.send(msg); }
void ExchangeStreamer::start() { webSocket.start(); }
void ExchangeStreamer::stop() { webSocket.stop(); }
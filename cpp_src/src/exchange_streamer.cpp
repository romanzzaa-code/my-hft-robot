#include "../include/exchange_streamer.hpp"
#include <iostream>
#include <ixwebsocket/IXNetSystem.h>

ExchangeStreamer::ExchangeStreamer(std::shared_ptr<IMessageParser> parser) 
    : parser_(parser) 
{
    ix::initNetSystem();
    // URL зависит от парсера, пока хардкодим для теста или берем из конфига
    // Для Bybit Linear:
    webSocket.setUrl("wss://stream.bybit.com/v5/public/linear");
    webSocket.setPingInterval(20);
    
    webSocket.setOnMessageCallback([this](const ix::WebSocketMessagePtr& msg) {
        this->on_message(msg);
    });
}

ExchangeStreamer::~ExchangeStreamer() {
    stop();
}

void ExchangeStreamer::add_symbol(const std::string& symbol) {
    symbols_.push_back(symbol);
    // В идеале тут надо слать JSON subscribe в сокет, если он уже запущен
}

void ExchangeStreamer::start() {
    webSocket.start();
    // Тут можно отправить subscribe на все symbols_
}

void ExchangeStreamer::stop() {
    webSocket.stop();
}

void ExchangeStreamer::set_tick_callback(std::function<void(const TickData&)> cb) {
    tick_cb_ = cb;
}

void ExchangeStreamer::set_orderbook_callback(std::function<void(const OrderBookSnapshot&)> cb) {
    depth_cb_ = cb;
}

void ExchangeStreamer::set_execution_callback(std::function<void(const ExecutionData&)> cb) {
    exec_cb_ = cb;
}

void ExchangeStreamer::on_message(const ix::WebSocketMessagePtr& msg) {
    if (msg->type == ix::WebSocketMessageType::Message) {
        // Парсинг...
        // Упрощенно вызываем парсер
        if (parser_) {
            // Тут должна быть логика вызова parser_->parse(...)
        }
    }
}
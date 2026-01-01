#pragma once
#include <string>
#include <vector>
#include <functional>
#include <memory>
#include <ixwebsocket/IXWebSocket.h>
#include "entities/tick_data.hpp"
#include "entities/market_depth.hpp"
#include "entities/execution_data.hpp"
#include "parsers/imessage_parser.hpp"

class ExchangeStreamer {
public:
    ExchangeStreamer(std::shared_ptr<IMessageParser> parser);
    ~ExchangeStreamer();

    void start();
    void stop();
    
    // Добавляем этот метод, чтобы main.cpp не ругался
    void add_symbol(const std::string& symbol); 

    void set_tick_callback(std::function<void(const TickData&)> cb);
    
    // Внимание: называем это set_orderbook_callback, чтобы совпадало с main.cpp
    // ИЛИ меняем в main.cpp. Давай поменяем тут, это проще.
    void set_orderbook_callback(std::function<void(const OrderBookSnapshot&)> cb);
    
    void set_execution_callback(std::function<void(const ExecutionData&)> cb);

private:
    void on_message(const ix::WebSocketMessagePtr& msg);
    
    ix::WebSocket webSocket;
    std::shared_ptr<IMessageParser> parser_;
    std::vector<std::string> symbols_;
    bool running_ = false;

    std::function<void(const TickData&)> tick_cb_;
    std::function<void(const OrderBookSnapshot&)> depth_cb_;
    std::function<void(const ExecutionData&)> exec_cb_;
};
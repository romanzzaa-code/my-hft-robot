#pragma once
#include <string>
#include <functional>
#include <memory>
#include <ixwebsocket/IXWebSocket.h>
#include "entities/tick_data.hpp"
#include "entities/market_depth.hpp"
#include "entities/ticker_data.hpp" // <--- 1. Не забудь этот инклюд!
#include "parsers/imessage_parser.hpp"

class ExchangeStreamer {
public:
    ExchangeStreamer(std::shared_ptr<IMessageParser> parser);
    ~ExchangeStreamer();

    void connect(std::string url);
    void start();
    void stop();
    void send_message(std::string msg);

    void set_tick_callback(std::function<void(const TickData&)> cb);
    void set_depth_callback(std::function<void(const OrderBookSnapshot&)> cb);
    
    // 2. ОБЯЗАТЕЛЬНО ОБЪЯВИТЬ ЭТОТ МЕТОД
    void set_ticker_callback(std::function<void(const TickerData&)> cb); 

private:
    ix::WebSocket webSocket;
    std::shared_ptr<IMessageParser> parser;
    
    std::function<void(const TickData&)> tick_callback;
    std::function<void(const OrderBookSnapshot&)> depth_callback;
    
    // 3. ОБЯЗАТЕЛЬНО ОБЪЯВИТЬ ЭТУ ПЕРЕМЕННУЮ
    std::function<void(const TickerData&)> ticker_callback;
};
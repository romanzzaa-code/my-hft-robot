#include "../include/exchange_streamer.hpp"
#include <iostream>
#include <ixwebsocket/IXNetSystem.h>
#include <nlohmann/json.hpp> // <--- ОБЯЗАТЕЛЬНО

ExchangeStreamer::ExchangeStreamer(std::shared_ptr<IMessageParser> parser) 
    : parser_(parser) 
{
    ix::initNetSystem();
    // Bybit Linear Public URL
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
    
    // ФИКС: Если сокет уже открыт — подписываемся мгновенно
    if (webSocket.getReadyState() == ix::ReadyState::Open) {
        nlohmann::json msg;
        msg["op"] = "subscribe";
        // Подписываемся на стакан (50 уровней) и сделки
        msg["args"] = {"orderbook.50." + symbol, "publicTrade." + symbol};
        webSocket.send(msg.dump());
        std::cout << "[C++] Dynamic Subscribe: " << symbol << std::endl;
    }
}

void ExchangeStreamer::start() {
    std::cout << "[C++] Starting Streamer..." << std::endl;
    webSocket.start();
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
    // 1. Обработка подключения
    if (msg->type == ix::WebSocketMessageType::Open) {
        std::cout << "[C++] Connected to Bybit Public Stream!" << std::endl;
        
        // ФИКС: Подписываемся на все накопленные символы при старте
        if (!symbols_.empty()) {
            nlohmann::json sub_msg;
            sub_msg["op"] = "subscribe";
            std::vector<std::string> args;
            for (const auto& s : symbols_) {
                args.push_back("orderbook.50." + s);
                args.push_back("publicTrade." + s);
            }
            sub_msg["args"] = args;
            webSocket.send(sub_msg.dump());
            std::cout << "[C++] Batch Subscribe for " << symbols_.size() << " symbols sent." << std::endl;
        }
    }
    // 2. Обработка данных
    else if (msg->type == ix::WebSocketMessageType::Message) {
        if (parser_) {
            TickData tick;
            OrderBookSnapshot depth;
            TickerData ticker;
            ExecutionData exec;
            
            // Парсим сообщение
            ParseResultType res = parser_->parse(msg->str, tick, depth, ticker, exec);
            
            // Роутинг
            if (res == ParseResultType::Trade && tick_cb_) {
                tick_cb_(tick);
            } 
            else if (res == ParseResultType::Depth && depth_cb_) {
                depth_cb_(depth);
            }
            // Execution и Ticker здесь обычно не прилетают (они в других потоках/топиках), 
            // но структуру сохраняем.
        }
    }
    // 3. Ошибки
    else if (msg->type == ix::WebSocketMessageType::Error) {
        std::cerr << "[C++] Streamer Error: " << msg->errorInfo.reason << std::endl;
    }
}
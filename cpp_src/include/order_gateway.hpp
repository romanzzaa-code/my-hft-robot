#pragma once
#include <string>
#include <functional>
#include <memory>
#include <ixwebsocket/IXWebSocket.h>

class OrderGateway {
public:
    OrderGateway(std::string api_key, std::string api_secret, bool testnet = false);
    ~OrderGateway();

    void connect();
    void stop();
    
    // Обновленная сигнатура с SL и TP
    void send_order(
        const std::string& symbol, 
        const std::string& side, 
        double qty, 
        double price,
        const std::string& order_link_id = "",
        const std::string& order_type = "Limit",
        const std::string& time_in_force = "PostOnly", 
        bool reduce_only = false,
        double stop_loss = 0.0,
        double take_profit = 0.0
    );
    
    void cancel_order(const std::string& symbol, const std::string& order_id);
    void set_on_order_update(std::function<void(const std::string&)> cb);

private:
    void authenticate();
    std::string generate_signature(long long expires);
    void on_message(const ix::WebSocketMessagePtr& msg);

    ix::WebSocket webSocket;
    std::string api_key_;
    std::string api_secret_;
    std::string url_;
    bool authenticated_ = false;
    
    std::function<void(const std::string&)> on_order_update_cb_;
};
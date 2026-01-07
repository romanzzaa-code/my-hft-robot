#pragma once
#include <string>
#include <functional>
#include <memory>
#include <ixwebsocket/IXWebSocket.h>

class OrderGateway {
public:
    // Конструктор принимает ключи API
    OrderGateway(std::string api_key, std::string api_secret, bool testnet = false);
    ~OrderGateway();

    // Управление соединением
    void connect();
    void stop();
    
    // МЕТОДЫ ТОРГОВЛИ (Вызываются из Python)
    // Отправка лимитного ордера
    void send_order(
        const std::string& symbol, 
        const std::string& side, 
        double qty, 
        double price,
        const std::string& order_link_id = "",       // Для отслеживания ордера
        const std::string& order_type = "Limit",     // "Limit" или "Market"
        const std::string& time_in_force = "PostOnly", // "PostOnly", "GTC", "IOC"
        bool reduce_only = false                     // Ваша защита
    );
    
    // Отмена ордера
    void cancel_order(const std::string& symbol, const std::string& order_id);

    // Коллбек для ответов биржи (проброс в Python)
    void set_on_order_update(std::function<void(const std::string&)> cb);

private:
    // Внутренняя логика
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
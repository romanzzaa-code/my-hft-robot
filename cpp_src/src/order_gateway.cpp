#include "../include/order_gateway.hpp"
#include <iostream>
#include <chrono>
#include <sstream>
#include <iomanip>
#include <openssl/hmac.h>
#include <nlohmann/json.hpp>
#include <ixwebsocket/IXNetSystem.h>

// Хелпер для форматирования чисел (убирает 1e-05)
std::string format_decimal(double value, int precision = 8) {
    std::stringstream ss;
    ss << std::fixed << std::setprecision(precision) << value;
    std::string s = ss.str();
    s.erase(s.find_last_not_of('0') + 1, std::string::npos);
    if (s.back() == '.') s.pop_back();
    return s;
}

std::string hmac_sha256(const std::string& key, const std::string& data) {
    unsigned char* digest;
    unsigned int len = 0;
    digest = HMAC(EVP_sha256(), 
                  (const void*)key.c_str(), key.length(), 
                  (const unsigned char*)data.c_str(), data.length(), 
                  NULL, &len);
    std::stringstream ss;
    for(unsigned int i = 0; i < len; i++) {
        ss << std::hex << std::setw(2) << std::setfill('0') << (int)digest[i];
    }
    return ss.str();
}

OrderGateway::OrderGateway(std::string key, std::string secret, bool testnet) 
    : api_key_(key), api_secret_(secret) 
{
    ix::initNetSystem();
    url_ = testnet ? "wss://stream-testnet.bybit.com/v5/trade" 
                   : "wss://stream.bybit.com/v5/trade";
    webSocket.setUrl(url_);
    webSocket.setPingInterval(20); 
    webSocket.setOnMessageCallback([this](const ix::WebSocketMessagePtr& msg) {
        this->on_message(msg);
    });
}

OrderGateway::~OrderGateway() {
    stop();
}

void OrderGateway::connect() {
    std::cout << "[C++] OrderGateway connecting to " << url_ << "..." << std::endl;
    webSocket.start();
}

void OrderGateway::stop() {
    webSocket.stop();
}

void OrderGateway::set_on_order_update(std::function<void(const std::string&)> cb) {
    on_order_update_cb_ = cb;
}

std::string OrderGateway::generate_signature(long long expires) {
    std::string val = "GET/realtime" + std::to_string(expires);
    return hmac_sha256(api_secret_, val);
}

void OrderGateway::authenticate() {
    auto now = std::chrono::system_clock::now();
    long long expires = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count() + 5000;
    std::string signature = generate_signature(expires);
    
    nlohmann::json auth_msg;
    auth_msg["op"] = "auth";
    auth_msg["args"] = {api_key_, expires, signature};
    webSocket.send(auth_msg.dump());
}

void OrderGateway::send_order(
    const std::string& symbol, const std::string& side, double qty, double price,
    const std::string& order_link_id, const std::string& order_type,
    const std::string& time_in_force, bool reduce_only,
    double stop_loss,
    double take_profit
) {
    if (!authenticated_) {
        std::cerr << "[C++] ERROR: Wait for Auth!" << std::endl;
        return;
    }

    nlohmann::json order;
    order["category"] = "linear";
    order["symbol"] = symbol;
    order["side"] = side; 
    order["orderType"] = order_type;
    order["qty"] = format_decimal(qty); 
    order["positionIdx"] = 0; // Fix One-Way Mode
    
    // Включаем Partial для поддержки лимитных тейков
    order["tpslMode"] = "Partial";

    if (order_type == "Limit") {
        order["price"] = format_decimal(price);
    }

    if (!order_link_id.empty()) order["orderLinkId"] = order_link_id;
    order["timeInForce"] = time_in_force;
    order["reduceOnly"] = reduce_only;

    // Атомарный Стоп (Рыночный)
    if (stop_loss > 0) {
        order["stopLoss"] = format_decimal(stop_loss);
        order["slOrderType"] = "Market";
    }

    // Атомарный Тейк (Лимитный)
    if (take_profit > 0) {
        std::string tp_str = format_decimal(take_profit);
        order["takeProfit"] = tp_str;
        order["tpOrderType"] = "Limit";
        order["tpLimitPrice"] = tp_str;
    }

    nlohmann::json msg;
    msg["op"] = "order.create"; 
    msg["args"] = {order};
    webSocket.send(msg.dump());
}

void OrderGateway::cancel_order(const std::string& symbol, const std::string& order_id) {
    if (!authenticated_) return;
    nlohmann::json cancel_req;
    cancel_req["category"] = "linear";
    cancel_req["symbol"] = symbol;
    cancel_req["orderId"] = order_id;
    nlohmann::json msg;
    msg["op"] = "order.cancel";
    msg["args"] = {cancel_req};
    webSocket.send(msg.dump());
}

void OrderGateway::on_message(const ix::WebSocketMessagePtr& msg) {
    if (msg->type == ix::WebSocketMessageType::Open) {
        std::cout << "[C++] Trade Stream Connected. Authenticating..." << std::endl;
        authenticate();
    } 
    else if (msg->type == ix::WebSocketMessageType::Message) {
        try {
            auto j = nlohmann::json::parse(msg->str);
            if (j.contains("op") && j["op"] == "auth") {
                bool ok_bool = j.value("success", false);
                int ret_code = j.value("retCode", -1);
                if (ok_bool || ret_code == 0) {
                    authenticated_ = true;
                    std::cout << "[C++] ✅ AUTH SUCCESS!" << std::endl;
                } else {
                    std::cerr << "[C++] ❌ AUTH FAILED: " << msg->str << std::endl;
                }
            }
            if (on_order_update_cb_) on_order_update_cb_(msg->str);
        } catch (...) {}
    }
}
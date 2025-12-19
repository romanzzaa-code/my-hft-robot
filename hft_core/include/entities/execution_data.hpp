#pragma once
#include <string>

struct ExecutionData {
    std::string symbol;
    std::string order_id;
    std::string side;
    double exec_price;
    double exec_qty;
    bool is_maker;
    long long timestamp;
};
    
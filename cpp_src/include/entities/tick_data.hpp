#pragma once
#include <string>

struct TickData {
    std::string symbol;
    double price;
    double qty;        // Было quantity? Стало qty
    long long timestamp;
    std::string side;  // Добавили side
};
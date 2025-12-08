#pragma once
#include <string>

struct TickData {
    std::string symbol;
    double price;
    double volume;
    long long timestamp;
};
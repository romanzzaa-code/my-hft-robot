use std::collections::BTreeMap;
use rust_decimal::Decimal;
use crate::{Price, Qty, Side, OrderBookLevel};

#[derive(Debug, Clone, Default)]
pub struct LocalOrderBook {
    bids: BTreeMap<Price, Qty>, 
    asks: BTreeMap<Price, Qty>, 
}

impl LocalOrderBook {
    pub fn new() -> Self {
        Self {
            bids: BTreeMap::new(),
            asks: BTreeMap::new(),
        }
    }

    pub fn apply_update(&mut self, bids: &[OrderBookLevel], asks: &[OrderBookLevel], is_snapshot: bool) {
        if is_snapshot {
            self.bids.clear();
            self.asks.clear();
        }

        for l in bids {
            if l.volume.is_zero() {
                self.bids.remove(&l.price);
            } else {
                self.bids.insert(l.price, l.volume);
            }
        }

        for l in asks {
            if l.volume.is_zero() {
                self.asks.remove(&l.price);
            } else {
                self.asks.insert(l.price, l.volume);
            }
        }
    }

    pub fn get_best(&self, side: Side) -> Option<Price> {
        match side {
            Side::Buy => self.bids.keys().next_back().cloned(), 
            Side::Sell => self.asks.keys().next().cloned(),     
        }
    }

    pub fn get_volume(&self, side: Side, price: Price) -> Qty {
        match side {
            Side::Buy => self.bids.get(&price).cloned().unwrap_or(Decimal::ZERO),
            Side::Sell => self.asks.get(&price).cloned().unwrap_or(Decimal::ZERO),
        }
    }

    pub fn get_background_volume(&self) -> Decimal {
        if self.bids.is_empty() || self.asks.is_empty() {
            return Decimal::ZERO;
        }

        let mut sum = Decimal::ZERO;
        let mut count = 0;

        for vol in self.bids.values().rev().skip(1).take(10) {
            sum += *vol;
            count += 1;
        }

        for vol in self.asks.values().skip(1).take(10) {
            sum += *vol;
            count += 1;
        }

        if count == 0 {
            return Decimal::ZERO;
        }

        sum / Decimal::from(count)
    }
}

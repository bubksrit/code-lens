"""Data models for the E-Commerce API."""
from dataclasses import dataclass, field
from typing import List, Optional
import time

@dataclass
class Product:
    product_id: str
    name: str
    price: float
    stock: int
    category: str
    description: str = ""

@dataclass
class OrderItem:
    product_id: str
    quantity: int
    unit_price: float

    @property
    def subtotal(self) -> float:
        return self.quantity * self.unit_price

@dataclass
class Order:
    order_id: str
    customer_id: str
    items: List[OrderItem] = field(default_factory=list)
    status: str = "pending"
    created_at: float = field(default_factory=time.time)

    @property
    def total_amount(self) -> float:
        return sum(item.subtotal for item in self.items)

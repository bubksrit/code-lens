"""Persistence layer for Order entities."""
from typing import List, Optional
from app.models import Order, OrderItem
from app.database import get_db


class OrderRepository:
    """Reads and writes Order records to the database."""

    def save_order(self, order: Order) -> str:
        """Persist a new Order and return its generated order_id.

        Args:
            order: The Order to persist.

        Returns:
            The order_id assigned to the stored record.
        """
        db = get_db()
        db.execute_write(
            "INSERT INTO orders (order_id, customer_id, status, created_at) VALUES (:id, :cid, :status, :ts)",
            {"id": order.order_id, "cid": order.customer_id, "status": order.status, "ts": order.created_at},
        )
        for item in order.items:
            db.execute_write(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (:oid, :pid, :qty, :price)",
                {"oid": order.order_id, "pid": item.product_id, "qty": item.quantity, "price": item.unit_price},
            )
        return order.order_id

    def find_order(self, order_id: str) -> Optional[Order]:
        """Retrieve an Order by its identifier.

        Args:
            order_id: The unique identifier to look up.

        Returns:
            The matching Order, or None if not found.
        """
        db = get_db()
        rows = db.execute_query("SELECT * FROM orders WHERE order_id = :id", {"id": order_id})
        if not rows:
            return None
        row = rows[0]
        items = self._load_items(order_id)
        return Order(
            order_id=row["order_id"],
            customer_id=row["customer_id"],
            items=items,
            status=row["status"],
        )

    def _load_items(self, order_id: str) -> List[OrderItem]:
        """Fetch all line items for a given order."""
        db = get_db()
        rows = db.execute_query("SELECT * FROM order_items WHERE order_id = :id", {"id": order_id})
        return [
            OrderItem(product_id=r["product_id"], quantity=r["quantity"], unit_price=r["unit_price"])
            for r in rows
        ]

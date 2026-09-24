"""Persistence layer for Product entities."""
from typing import List, Optional
from app.models import Product
from app.database import get_db


class ProductRepository:
    """Reads Product records from the database."""

    def find_product(self, product_id: str) -> Optional[Product]:
        """Look up a product by its unique identifier.

        Args:
            product_id: The product identifier to search for.

        Returns:
            The matching Product, or None if not found.
        """
        db = get_db()
        rows = db.execute_query("SELECT * FROM products WHERE product_id = :id", {"id": product_id})
        if not rows:
            return None
        r = rows[0]
        return Product(
            product_id=r["product_id"],
            name=r["name"],
            price=float(r["price"]),
            stock=int(r["stock"]),
            category=r["category"],
        )

    def list_products(self, category: Optional[str] = None) -> List[Product]:
        """Return all products, optionally filtered by category."""
        db = get_db()
        if category:
            rows = db.execute_query("SELECT * FROM products WHERE category = :cat", {"cat": category})
        else:
            rows = db.execute_query("SELECT * FROM products", {})
        return [
            Product(product_id=r["product_id"], name=r["name"], price=float(r["price"]), stock=int(r["stock"]), category=r["category"])
            for r in rows
        ]

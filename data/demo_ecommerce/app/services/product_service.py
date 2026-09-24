"""Business logic for Product management in the E-Commerce API."""
from typing import List, Optional
from app.models import Product
from app.repositories.product_repository import ProductRepository


class ProductService:
    """Coordinates product lookups and availability checks."""

    def __init__(self) -> None:
        self._product_repo = ProductRepository()

    def get_product(self, product_id: str) -> Optional[Product]:
        """Return a product by ID, or None if it does not exist.

        Args:
            product_id: The unique product identifier.

        Returns:
            Matching Product or None.
        """
        return self._product_repo.find_product(product_id)

    def list_by_category(self, category: str) -> List[Product]:
        """Return all products belonging to a specific category."""
        return self._product_repo.list_products(category=category)

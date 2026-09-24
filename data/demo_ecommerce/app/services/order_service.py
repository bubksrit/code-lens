"""Business logic for Order processing in the E-Commerce API."""
import uuid
from typing import Optional
from app.models import Order, OrderItem
from app.validation import validate_order_input, check_product_availability
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository


class OrderService:
    """Coordinates order creation and retrieval across validation and persistence layers."""

    def __init__(self) -> None:
        self._order_repo = OrderRepository()
        self._product_repo = ProductRepository()

    def process_order(self, payload: dict) -> Order:
        """Validate, enrich, and persist a new customer order.

        Steps:
        1. Validate raw input via validate_order_input.
        2. Resolve each product and check availability via check_product_availability.
        3. Construct the Order and persist via OrderRepository.

        Args:
            payload: Raw order request with 'customer_id' and 'items' list.

        Returns:
            The created and persisted Order object.

        Raises:
            ValueError: If validation fails or a product is unavailable.
        """
        is_valid, errors = validate_order_input(payload)
        if not is_valid:
            raise ValueError(f"Order validation failed: {'; '.join(errors)}")

        items = []
        for raw_item in payload["items"]:
            product = self._product_repo.find_product(raw_item["product_id"])
            if product is None:
                raise ValueError(f"Product '{raw_item['product_id']}' not found.")
            available, reason = check_product_availability(product, raw_item["quantity"])
            if not available:
                raise ValueError(reason)
            items.append(OrderItem(
                product_id=product.product_id,
                quantity=raw_item["quantity"],
                unit_price=product.price,
            ))

        order = Order(
            order_id=str(uuid.uuid4()),
            customer_id=payload["customer_id"],
            items=items,
            status="pending",
        )
        self._order_repo.save_order(order)
        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        """Retrieve an existing order by ID.

        Args:
            order_id: The order identifier.

        Returns:
            The matching Order, or None if not found.
        """
        return self._order_repo.find_order(order_id)

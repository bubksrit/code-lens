"""Input validation for the E-Commerce API."""
from typing import Dict, List, Optional, Tuple
from app.models import Order, OrderItem, Product


def validate_order_input(payload: Dict) -> Tuple[bool, List[str]]:
    """Validate a raw order creation payload before processing.

    Checks that required fields are present, that item quantities are positive,
    and that the total item count does not exceed the maximum allowed.

    Args:
        payload: Raw request dictionary containing 'customer_id' and 'items'.

    Returns:
        A tuple of (is_valid, list_of_error_messages).
    """
    errors: List[str] = []

    if not payload.get("customer_id"):
        errors.append("customer_id is required.")

    items = payload.get("items", [])
    if not items:
        errors.append("Order must contain at least one item.")

    for idx, item in enumerate(items):
        if item.get("quantity", 0) <= 0:
            errors.append(f"Item {idx}: quantity must be positive.")
        if not item.get("product_id"):
            errors.append(f"Item {idx}: product_id is required.")

    if len(items) > 50:
        errors.append("Order cannot contain more than 50 items.")

    return (len(errors) == 0, errors)


def check_product_availability(product: Product, requested_quantity: int) -> Tuple[bool, str]:
    """Verify that sufficient stock exists for a product.

    Args:
        product: The Product to check.
        requested_quantity: How many units the customer wants.

    Returns:
        Tuple of (is_available, reason_string).
    """
    if product.stock <= 0:
        return (False, f"Product '{product.name}' is out of stock.")
    if product.stock < requested_quantity:
        return (False, f"Only {product.stock} units of '{product.name}' available; {requested_quantity} requested.")
    return (True, "")


def validate_customer_id(customer_id: str) -> bool:
    """Check that customer_id is a non-empty alphanumeric string."""
    return bool(customer_id) and customer_id.replace("-", "").replace("_", "").isalnum()

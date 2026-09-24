"""HTTP route handlers for the E-Commerce API."""
from typing import Any, Dict
from app.services.order_service import OrderService
from app.services.product_service import ProductService
from app.validation import validate_order_input

_order_service = OrderService()
_product_service = ProductService()


def create_order_endpoint(request_body: Dict[str, Any]) -> Dict[str, Any]:
    """Handle POST /orders — create a new customer order.

    Validates input, delegates to OrderService.process_order, and returns
    the serialised order with HTTP 201.

    Args:
        request_body: Parsed JSON body with 'customer_id' and 'items'.

    Returns:
        Dict with 'order_id', 'status', and 'total_amount'.

    Raises:
        ValueError: Propagated from OrderService on validation failure.
    """
    order = _order_service.process_order(request_body)
    return {
        "order_id": order.order_id,
        "status": order.status,
        "total_amount": order.total_amount,
        "item_count": len(order.items),
    }


def get_order_endpoint(order_id: str) -> Dict[str, Any]:
    """Handle GET /orders/{order_id} — retrieve an existing order.

    Args:
        order_id: The order UUID path parameter.

    Returns:
        Serialised order dict, or raises 404 if not found.
    """
    order = _order_service.get_order(order_id)
    if order is None:
        raise LookupError(f"Order '{order_id}' not found.")
    return {"order_id": order.order_id, "status": order.status, "total_amount": order.total_amount}


def get_product_endpoint(product_id: str) -> Dict[str, Any]:
    """Handle GET /products/{product_id} — retrieve a product.

    Args:
        product_id: The product identifier path parameter.

    Returns:
        Serialised product dict.
    """
    product = _product_service.get_product(product_id)
    if product is None:
        raise LookupError(f"Product '{product_id}' not found.")
    return {
        "product_id": product.product_id,
        "name": product.name,
        "price": product.price,
        "stock": product.stock,
    }

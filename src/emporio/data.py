"""Loading, normalization and validation of the store's CSV data.

The CSVs are small (tens of rows), so everything is loaded into memory as
typed pydantic models. Inconsistencies are not silently fixed: they are
collected in `StoreData.issues` so they can be reviewed and documented.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
FILE_PREFIX = "desafio_tecnico_ai_eng - "

ProductStatus = Literal["active", "discontinued", "coming_soon"]
OrderStatus = Literal["pending", "confirmed", "shipped", "delivered", "cancelled"]

# Brands present in the catalog. Used to detect descriptions that mention a
# brand different from the product name (the name is the source of truth).
KNOWN_BRANDS = [
    "Crafter", "Fender", "Giannini", "Gibson", "Ibanez", "Kala", "Kalani", "Korg", "Martin",
    "Music Man", "Nord", "Ohana", "Pearl", "PRS", "Roland", "Rozini", "Shelby", "Tagima",
    "Takamine", "Taylor", "Yamaha",
]


def brands_in(text: str) -> set[str]:
    return {b for b in KNOWN_BRANDS if re.search(rf"\b{re.escape(b)}\b", text, re.IGNORECASE)}


def _empty_to_none(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


class Category(BaseModel):
    category_id: int
    name: str
    description: str


class Product(BaseModel):
    product_id: int
    name: str
    price_brl: float
    category_id: int
    description: str
    stock_quantity: int
    status: ProductStatus
    specs: dict
    created_at: date

    @field_validator("specs", mode="before")
    @classmethod
    def parse_specs(cls, value):
        if isinstance(value, str):
            return json.loads(value) if value.strip() else {}
        return value or {}

    @property
    def is_available(self) -> bool:
        return self.status == "active" and self.stock_quantity > 0


class Promotion(BaseModel):
    promotion_id: int
    product_id: int
    discount_percent: float
    description: str
    is_active: bool


class Customer(BaseModel):
    customer_id: int
    name: str
    phone: str
    email: str
    city: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class OrderItem(BaseModel):
    order_id: int
    product_id: int
    quantity: int


class Order(BaseModel):
    order_id: int
    customer_id: int
    order_date: date
    status: OrderStatus
    total_brl: float
    payment_method: str
    tracking_code: Optional[str] = None
    estimated_delivery: Optional[date] = None
    notes: Optional[str] = None

    _normalize_optional = field_validator(
        "tracking_code", "estimated_delivery", "notes", mode="before"
    )(_empty_to_none)


@dataclass
class StoreData:
    categories: dict[int, Category]
    products: dict[int, Product]
    promotions: list[Promotion]
    customers: dict[int, Customer]
    orders: dict[int, Order]
    order_items: dict[int, list[OrderItem]]
    issues: list[str] = field(default_factory=list)

    def active_promotion(self, product_id: int) -> Optional[Promotion]:
        """Best active promotion for a product (promotions are not cumulative)."""
        active = [
            p for p in self.promotions if p.product_id == product_id and p.is_active
        ]
        return max(active, key=lambda p: p.discount_percent, default=None)


def _read_csv(data_dir: Path, table: str) -> list[dict]:
    path = data_dir / f"{FILE_PREFIX}{table}.csv"
    with path.open(encoding="utf-8", newline="") as f:
        return [{k.strip(): _empty_to_none(v) for k, v in row.items()} for row in csv.DictReader(f)]


def load_store(data_dir: Path = DATA_DIR) -> StoreData:
    categories = {c.category_id: c for c in map(Category.model_validate, _read_csv(data_dir, "categories"))}
    products = {p.product_id: p for p in map(Product.model_validate, _read_csv(data_dir, "products"))}
    promotions = [Promotion.model_validate(r) for r in _read_csv(data_dir, "promotions")]
    customers = {c.customer_id: c for c in map(Customer.model_validate, _read_csv(data_dir, "customers"))}
    orders = {o.order_id: o for o in map(Order.model_validate, _read_csv(data_dir, "orders"))}

    order_items: dict[int, list[OrderItem]] = defaultdict(list)
    for row in _read_csv(data_dir, "order_items"):
        item = OrderItem.model_validate(row)
        order_items[item.order_id].append(item)

    store = StoreData(categories, products, promotions, customers, orders, dict(order_items))
    store.issues = validate(store)
    return store


def validate(store: StoreData) -> list[str]:
    """Cross-table consistency checks. Returns human-readable issue descriptions."""
    issues: list[str] = []

    for p in store.products.values():
        if p.category_id not in store.categories:
            issues.append(f"Product {p.product_id} references unknown category {p.category_id}.")
        if p.status == "active" and p.stock_quantity == 0:
            issues.append(f"Product {p.product_id} ({p.name}) is active but out of stock.")
        if p.status != "active" and p.stock_quantity > 0:
            issues.append(
                f"Product {p.product_id} ({p.name}) has status '{p.status}' but stock {p.stock_quantity}."
            )
        other_brands = brands_in(p.description) - brands_in(p.name)
        if other_brands:
            issues.append(
                f"Product {p.product_id} ({p.name}) description mentions another brand: "
                f"{', '.join(sorted(other_brands))}."
            )

    used_categories = {p.category_id for p in store.products.values()}
    for c in store.categories.values():
        if c.category_id not in used_categories:
            issues.append(f"Category {c.category_id} ({c.name}) has no products.")

    promo_count = Counter(p.product_id for p in store.promotions)
    for product_id, count in promo_count.items():
        if count > 1:
            issues.append(f"Product {product_id} has {count} promotion records.")
    for promo in store.promotions:
        product = store.products.get(promo.product_id)
        if product is None:
            issues.append(f"Promotion {promo.promotion_id} references unknown product {promo.product_id}.")
        elif promo.is_active and product.status != "active":
            issues.append(
                f"Promotion {promo.promotion_id} is active for product {product.product_id} "
                f"with status '{product.status}'."
            )

    for order in store.orders.values():
        if order.customer_id not in store.customers:
            issues.append(f"Order {order.order_id} references unknown customer {order.customer_id}.")
        items = store.order_items.get(order.order_id, [])
        if not items:
            issues.append(f"Order {order.order_id} has no items.")
            continue
        computed = 0.0
        for item in items:
            product = store.products.get(item.product_id)
            if product is None:
                issues.append(f"Order {order.order_id} references unknown product {item.product_id}.")
                continue
            computed += product.price_brl * item.quantity
            if product.status == "coming_soon" and order.status != "cancelled":
                issues.append(
                    f"Order {order.order_id} ({order.status}) contains product {product.product_id} "
                    f"which is 'coming_soon'."
                )
        if abs(computed - order.total_brl) > 0.01:
            issues.append(
                f"Order {order.order_id} total is R$ {order.total_brl:.2f} but items sum to "
                f"R$ {computed:.2f} at current prices."
            )
        if order.status in ("shipped", "delivered") and not order.tracking_code:
            issues.append(f"Order {order.order_id} is '{order.status}' without a tracking code.")

    return issues


if __name__ == "__main__":
    data = load_store()
    print(
        f"Loaded {len(data.products)} products, {len(data.categories)} categories, "
        f"{len(data.promotions)} promotions, {len(data.customers)} customers, "
        f"{len(data.orders)} orders."
    )
    print(f"\n{len(data.issues)} data issues found:")
    for issue in data.issues:
        print(f"  - {issue}")

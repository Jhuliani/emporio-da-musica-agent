from emporio.data import load_store


def test_loads_all_tables():
    store = load_store()
    assert len(store.products) == 65
    assert len(store.categories) == 9
    assert len(store.orders) == 20
    assert sum(len(items) for items in store.order_items.values()) == 22


def test_specs_are_parsed_as_dict():
    store = load_store()
    assert store.products[81].specs["strings"] == "nylon"


def test_optional_order_fields_are_none_when_empty():
    order = load_store().orders[9]
    assert order.tracking_code is None
    assert order.estimated_delivery is None


def test_active_promotion_ignores_inactive_records():
    store = load_store()
    assert store.active_promotion(95) is None  # Takamine GD20: only an expired promotion
    assert store.active_promotion(94).discount_percent == 8


def test_known_inconsistencies_are_reported():
    issues = "\n".join(load_store().issues)
    assert "Product 96" in issues and "out of stock" in issues
    assert "Order 3 total" in issues
    assert "Category 8" in issues
    assert "Product 135 (Music Man Bass 1X Electric Bass) description mentions another brand: Fender" in issues

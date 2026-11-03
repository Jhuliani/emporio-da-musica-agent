from datetime import date, datetime

import pytest

from emporio.data import load_store
from emporio.rules import (
    STORE_TZ,
    availability,
    installment_options,
    payment_method_label,
    payment_summary,
    price_quote,
    return_eligibility,
    shipping_quote,
    store_status,
)


@pytest.fixture(scope="module")
def store():
    return load_store()


# --- Prices and promotions ---------------------------------------------------

def test_expired_promotion_is_not_applied(store):
    quote = price_quote(store.products[95], store)  # Takamine GD20
    assert quote["promotion"] is None
    assert quote["price"] == 2199.0
    assert quote["pix_price"] == pytest.approx(2089.05)


def test_active_promotion_disables_pix_discount(store):
    quote = price_quote(store.products[94], store)  # Taylor 110e, 8% active
    assert quote["promotion"]["discount_percent"] == 8
    assert quote["price"] == pytest.approx(5519.08)
    assert quote["pix_price"] == quote["price"]
    assert quote["pix_discount_applies"] is False


# --- Availability ------------------------------------------------------------

@pytest.mark.parametrize(
    "product_id, expected",
    [(81, "in_stock"), (96, "out_of_stock"), (113, "discontinued"),
     (136, "discontinued"), (130, "coming_soon")],
)
def test_status_prevails_over_stock(store, product_id, expected):
    assert availability(store.products[product_id]) == expected


# --- Installments ------------------------------------------------------------

def test_installments_respect_tier_minimums():
    options = {o["installments"]: o["value"] for o in installment_options(450)}
    assert 3 in options  # 150 >= 50
    assert 5 in options  # 90 >= 80
    assert 6 not in options  # 75 < 80
    assert 7 not in options  # 64.28 < 100


def test_cheap_item_only_allows_few_installments():
    assert [o["installments"] for o in installment_options(120)] == [1, 2]


def test_expensive_item_allows_12x():
    assert installment_options(2199)[-1] == {"installments": 12, "value": 183.25}


def test_payment_summary_combined_payment_threshold():
    assert payment_summary(2000)["combined_payment_allowed"] is False
    assert payment_summary(2000.01)["combined_payment_allowed"] is True


def test_payment_method_label():
    assert payment_method_label("credit_6x") == "cartão de crédito em 6x"
    assert payment_method_label("pix") == "PIX"


# --- Shipping ----------------------------------------------------------------

def test_metro_shipping_is_free_only_above_500():
    assert shipping_quote(500.01, "Campo Grande")["fee"] == 0
    assert shipping_quote(500, "Campo Grande")["fee"] == 35


def test_other_cities_fee_is_not_invented():
    quote = shipping_quote(3000, "Dourados")
    assert quote["fee"] is None
    assert "SEDEX" in quote["options"]


# --- Returns and exchanges ---------------------------------------------------

def test_withdrawal_within_7_days_of_receipt(store):
    order = store.orders[1]  # delivered, estimated delivery 2025-10-25
    assert return_eligibility(order, date(2025, 11, 1))["withdrawal"]["eligible"] is True
    assert return_eligibility(order, date(2025, 11, 2))["withdrawal"]["eligible"] is False


def test_withdrawal_not_available_before_delivery(store):
    result = return_eligibility(store.orders[8], date(2026, 3, 1))  # shipped
    assert result["withdrawal"]["eligible"] is False


def test_defect_exchange_counts_from_purchase(store):
    order = store.orders[1]  # purchased 2025-10-15
    assert return_eligibility(order, date(2025, 11, 14))["defect_exchange"]["eligible"] is True
    assert return_eligibility(order, date(2025, 11, 15))["defect_exchange"]["eligible"] is False


# --- Opening hours -----------------------------------------------------------

def test_open_on_weekday_afternoon():
    status = store_status(datetime(2026, 11, 3, 15, 0, tzinfo=STORE_TZ))  # Tuesday
    assert status["is_open"] is True
    assert status["closes_at"] == "18:00"


def test_saturday_closes_at_13():
    status = store_status(datetime(2026, 11, 7, 13, 30, tzinfo=STORE_TZ))  # Saturday
    assert status["is_open"] is False
    assert status["next_opening"].startswith("segunda")


def test_sunday_closed_opens_monday():
    status = store_status(datetime(2026, 11, 8, 10, 0, tzinfo=STORE_TZ))
    assert status["is_open"] is False
    assert status["next_opening"] == "segunda (09/11) às 09:00"


def test_before_opening_same_day():
    status = store_status(datetime(2026, 11, 3, 7, 0, tzinfo=STORE_TZ))
    assert status["next_opening"] == "terça (03/11) às 09:00"

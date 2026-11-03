import json
from datetime import datetime

import pytest

from emporio.data import load_store
from emporio.rules import STORE_TZ
from emporio.tools import StoreTools, TOOL_NAMES, tool_schemas

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=STORE_TZ)


@pytest.fixture
def tools(tmp_path):
    return StoreTools(load_store(), now=lambda: NOW, handoff_file=tmp_path / "handoffs.jsonl")


def names(result):
    return [p["name"] for p in result["products"]]


# --- search_products ---------------------------------------------------------

def test_guitars_up_to_1000_exclude_unavailable(tools):
    result = tools.search_products(category="Violões", max_price=1000)
    ids = [p["product_id"] for p in result["products"]]
    assert 96 not in ids  # out of stock
    assert 113 not in ids  # discontinued
    assert all(p["price"] <= 1000 for p in result["products"])
    assert result["products"] == sorted(result["products"], key=lambda p: p["price"])
    assert any("Giannini GF-3D" in m["name"] for m in result["unavailable_matches"])


def test_search_is_accent_insensitive_and_uses_category_words(tools):
    with_accent = tools.search_products(query="violão", limit=100)
    without = tools.search_products(query="violao", limit=100)
    assert with_accent["total_found"] == without["total_found"] > 0


def test_search_matches_whole_words_only(tools):
    assert tools.search_products(query="viola")["total_found"] == 0


def test_empty_category_returns_nothing(tools):
    result = tools.search_products(category="Instrumentos de Sopro (Metais)")
    assert result["total_found"] == 0


def test_unknown_category_returns_valid_options(tools):
    result = tools.search_products(category="Amplificadores")
    assert "error" in result and "Violões" in result["valid_categories"]


# --- get_product ---------------------------------------------------------------

def test_get_product_by_name_without_expired_promotion(tools):
    result = tools.get_product(name="Takamine GD20")
    assert result["product_id"] == 95
    assert result["promotion"] is None
    assert result["price"] == 2199.0
    assert result["payment"]["credit_max_installments"] == 12


def test_unavailable_product_suggests_in_stock_alternatives(tools):
    result = tools.get_product(product_id=136)  # discontinued bass
    assert result["availability"] == "discontinued"
    assert result["alternatives"]
    assert all(a["availability"] == "in_stock" for a in result["alternatives"])


def test_unknown_product(tools):
    assert "error" in tools.get_product(name="Saxofone Selmer")


# --- promotions --------------------------------------------------------------

def test_active_promotions_only(tools):
    ids = {p["product_id"] for p in tools.list_active_promotions()["active_promotions"]}
    assert ids == {90, 94, 121, 127}


# --- get_order_status ----------------------------------------------------------

def test_order_requires_matching_contact(tools):
    result = tools.get_order_status(order_id=1, email_or_phone="someone@else.com")
    assert result["verified"] is False
    assert "Martin" not in json.dumps(result)


def test_unknown_order_gives_same_answer_as_wrong_contact(tools):
    assert tools.get_order_status(999, "x@y.com") == tools.get_order_status(1, "x@y.com")


@pytest.mark.parametrize("contact", ["PEDRO.OLIVEIRA@jmail.com", "(67) 98432-1098", "984321098"])
def test_order_verified_by_email_or_phone(tools, contact):
    result = tools.get_order_status(order_id=1, email_or_phone=contact)
    assert result["verified"] is True
    assert result["customer_first_name"] == "Pedro"
    assert result["items"][0]["product"].startswith("Martin D-28")


def test_shipped_order_past_estimate_is_flagged_as_delayed(tools):
    result = tools.get_order_status(order_id=8, email_or_phone="(67) 99654-7821")
    assert result["delayed"] is True
    assert result["days_late"] > 200


def test_cancelled_order_shows_reason(tools):
    result = tools.get_order_status(order_id=18, email_or_phone=tools.store.customers[17].email)
    assert result["status"] == "cancelled"
    assert "fora de estoque" in result["notes"]


# --- simulate_payment / store status / escalation -------------------------------

def test_simulate_payment_for_promoted_product_has_no_pix_discount(tools):
    result = tools.simulate_payment(product_id=94)
    assert result["pix_discount_applies"] is False


def test_simulate_payment_with_shipping(tools):
    result = tools.simulate_payment(amount=300, city="Campo Grande")
    assert result["shipping"]["fee"] == 35


def test_store_status_uses_injected_clock(tools):
    assert tools.get_store_status()["is_open"] is True


def test_escalation_is_persisted(tools):
    result = tools.escalate_to_human(reason="complaint", summary="Pedido atrasado")
    assert result["registered"] is True
    ticket = json.loads(tools.handoff_file.read_text(encoding="utf-8").strip())
    assert ticket["summary"] == "Pedido atrasado"


# --- dispatch and schemas --------------------------------------------------------

def test_execute_handles_unknown_tool_and_bad_arguments(tools):
    assert "error" in tools.execute("drop_tables", {})
    assert "error" in tools.execute("get_order_status", {"order_id": 1})


def test_every_schema_has_an_implementation(tools):
    schema_names = {s["function"]["name"] for s in tool_schemas(tools.store)}
    assert schema_names == TOOL_NAMES
    assert all(callable(getattr(tools, n)) for n in schema_names)

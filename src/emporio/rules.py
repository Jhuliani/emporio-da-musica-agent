"""Deterministic business rules from the store policy manual.

Anything involving money, dates or availability is computed here, never by the
LLM: a wrong price or deadline can amount to misleading advertising (manual 7.1).
Interpretations of ambiguous rules are documented in docs/data_quality.md.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from emporio.data import Order, Product, StoreData

# Mato Grosso do Sul is UTC-4 with no daylight saving time (abolished in 2019),
# so a fixed offset avoids depending on the OS timezone database.
STORE_TZ = timezone(timedelta(hours=-4))

PIX_DISCOUNT = 0.05
MAX_INSTALLMENTS = 12
# (max installments in tier, minimum value of each installment) — manual 3.1
INSTALLMENT_TIERS = [(3, 50.0), (6, 80.0), (12, 100.0)]
COMBINED_PAYMENT_MIN = 2000.0

METRO_FREE_SHIPPING_ABOVE = 500.0
METRO_SHIPPING_FEE = 35.0
METRO_CITIES = {"campo grande"}

WITHDRAWAL_DAYS = 7  # right of withdrawal, from receipt (4.1)
DEFECT_EXCHANGE_DAYS = 30  # from purchase (4.2)
LEGAL_WARRANTY_DAYS = 90  # from receipt (8.1)

# weekday() -> (opening, closing); Sunday closed (manual 2)
OPENING_HOURS = {
    **{d: (time(9), time(18)) for d in range(5)},
    5: (time(9), time(13)),
}
WEEKDAY_NAMES = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

ORDER_STATUS_LABELS = {
    "pending": "aguardando pagamento/processamento",
    "confirmed": "confirmado, em preparação para envio",
    "shipped": "enviado",
    "delivered": "entregue",
    "cancelled": "cancelado",
}


def brl(value: float) -> str:
    """429.9 -> 'R$ 429,90' (formatted in code: the LLM once wrote 'R$ 429,00')."""
    return "R$ " + f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def payment_method_label(code: str) -> str:
    """'credit_6x' -> 'cartão de crédito em 6x'."""
    labels = {"pix": "PIX", "debit": "cartão de débito", "boleto": "boleto bancário"}
    if code in labels:
        return labels[code]
    if code.startswith("credit_"):
        return f"cartão de crédito em {code.removeprefix('credit_')}"
    return code


def price_quote(product: Product, store: StoreData) -> dict:
    """Current price of a product, applying the active promotion or the PIX discount.

    Promotions are not cumulative and PIX's 5% does not apply over promotional
    prices (manual 6.2).
    """
    promo = store.active_promotion(product.product_id)
    quote = {
        "list_price": round(product.price_brl, 2),
        "promotion": None,
        "price": round(product.price_brl, 2),
        "pix_price": round(product.price_brl * (1 - PIX_DISCOUNT), 2),
        "pix_discount_applies": True,
    }
    if promo:
        promo_price = round(product.price_brl * (1 - promo.discount_percent / 100), 2)
        quote.update(
            promotion={"name": promo.description, "discount_percent": promo.discount_percent},
            price=promo_price,
            pix_price=promo_price,
            pix_discount_applies=False,
        )
    return quote


def availability(product: Product) -> str:
    """Status prevails over stock (see data_quality.md, 1.1–1.3)."""
    if product.status == "discontinued":
        return "discontinued"
    if product.status == "coming_soon":
        return "coming_soon"
    return "in_stock" if product.stock_quantity > 0 else "out_of_stock"


def installment_options(amount: float) -> list[dict]:
    """Interest-free credit card installments allowed for an amount (manual 3.1)."""
    options = []
    for n in range(1, MAX_INSTALLMENTS + 1):
        minimum = next(m for max_n, m in INSTALLMENT_TIERS if n <= max_n)
        value = round(amount / n, 2)
        if n == 1 or value >= minimum:
            options.append({"installments": n, "value": value})
    return options


def payment_summary(amount: float, has_promotion: bool = False) -> dict:
    max_option = installment_options(amount)[-1]
    return {
        "amount": round(amount, 2),
        "pix": round(amount if has_promotion else amount * (1 - PIX_DISCOUNT), 2),
        "pix_discount_applies": not has_promotion,
        "debit": round(amount, 2),
        "boleto": round(amount, 2),
        "credit_max_installments": max_option["installments"],
        "credit_installment_value": max_option["value"],
        "credit_options": installment_options(amount),
        "combined_payment_allowed": amount > COMBINED_PAYMENT_MIN,
    }


def shipping_quote(subtotal: float, city: str) -> dict:
    """Shipping rules (manual 5). Only the Campo Grande metro fee is computable.

    "Acima de R$ 500" is read strictly: exactly R$ 500 pays the fixed fee.
    """
    if city.strip().lower() in METRO_CITIES:
        free = subtotal > METRO_FREE_SHIPPING_ABOVE
        return {
            "region": "metro",
            "fee": 0.0 if free else METRO_SHIPPING_FEE,
            "delivery_time": "1 a 3 dias úteis (motoboy próprio)",
        }
    return {
        "region": "other",
        "fee": None,
        "fee_note": "calculado no fechamento da compra (CEP, peso e dimensões)",
        "options": {
            "PAC": "5 a 12 dias úteis",
            "SEDEX": "2 a 5 dias úteis",
            "Jadlog": "3 a 8 dias úteis",
        },
    }


def return_eligibility(order: Order, today: date) -> dict:
    """Return/exchange windows for an order (manual 4 and 8).

    There is no actual delivery date in the data, so `estimated_delivery` is
    used as the receipt date (data_quality.md, 3.3).
    """
    result = {"order_status": order.status, "purchase_date": order.order_date.isoformat()}

    defect_deadline = order.order_date + timedelta(days=DEFECT_EXCHANGE_DAYS)
    result["defect_exchange"] = {
        "deadline": defect_deadline.isoformat(),
        "eligible": order.status == "delivered" and today <= defect_deadline,
    }

    if order.status != "delivered" or order.estimated_delivery is None:
        result["withdrawal"] = {
            "eligible": False,
            "reason": "pedido ainda não foi entregue" if order.status != "cancelled" else "pedido cancelado",
        }
        return result

    receipt = order.estimated_delivery
    withdrawal_deadline = receipt + timedelta(days=WITHDRAWAL_DAYS)
    result["receipt_date_estimated"] = receipt.isoformat()
    result["withdrawal"] = {
        "deadline": withdrawal_deadline.isoformat(),
        "eligible": today <= withdrawal_deadline,
        "days_left": max((withdrawal_deadline - today).days, 0),
        "note": "data de recebimento estimada; casos no limite devem ser confirmados pela equipe",
    }
    warranty_deadline = receipt + timedelta(days=LEGAL_WARRANTY_DAYS)
    result["legal_warranty"] = {
        "deadline": warranty_deadline.isoformat(),
        "active": today <= warranty_deadline,
    }
    return result


def store_status(now: Optional[datetime] = None) -> dict:
    """Whether the store is open now and when it opens next (holidays not modeled)."""
    now = (now or datetime.now(STORE_TZ)).astimezone(STORE_TZ)
    hours = OPENING_HOURS.get(now.weekday())
    is_open = bool(hours) and hours[0] <= now.time() < hours[1]

    next_opening = None
    if not is_open:
        for offset in range(0, 8):
            day = now.date() + timedelta(days=offset)
            day_hours = OPENING_HOURS.get(day.weekday())
            if day_hours and (offset > 0 or now.time() < day_hours[0]):
                next_opening = f"{WEEKDAY_NAMES[day.weekday()]} ({day.strftime('%d/%m')}) às {day_hours[0].strftime('%H:%M')}"
                break

    return {
        "now": now.strftime("%Y-%m-%d %H:%M"),
        "weekday": WEEKDAY_NAMES[now.weekday()],
        "is_open": is_open,
        "closes_at": hours[1].strftime("%H:%M") if is_open else None,
        "next_opening": next_opening,
        "note": "a loja fecha em feriados",
    }

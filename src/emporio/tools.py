"""Tools exposed to the LLM via function calling.

Each tool returns a JSON-serializable dict built from the store data and the
deterministic rules in `rules.py`. The LLM decides *when* to call a tool and how
to phrase the answer, but never computes prices, dates or availability itself.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional

from emporio import rules
from emporio.data import Product, StoreData, brands_in, digits_only

HANDOFF_FILE = Path(__file__).resolve().parents[2] / "logs" / "handoffs.jsonl"
LAST_UNITS = 2  # stock at or below this is shown as "últimas unidades"

# Singular/plural and common words customers use for each category, so that
# a search for "violão" finds products in "Violões".
CATEGORY_KEYWORDS = {
    1: "guitarra guitarras eletrica",
    2: "baixo baixos contrabaixo",
    3: "bateria baterias percussao",
    4: "teclado teclados piano pianos sintetizador synth",
    5: "violao violoes",
    6: "sopro flauta clarinete saxofone sax oboe",
    7: "sopro metais trompete trombone tuba trompa",
    8: "violino viola violoncelo cello contrabaixo acustico",
    9: "ukulele ukuleles",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


# Words that carry no meaning for product search ("violão para iniciante").
STOPWORDS = set(
    "a o as os um uma uns umas de do da dos das em no na nos nas para pra por com sem e ou "
    "que qual quais quanto custa preco valor tem voces vcs quero queria gostaria me um algum "
    "alguma modelo produto instrumento ate mais muito bom boa".split()
)


def tokenize(text: str) -> list[str]:
    """Accent-insensitive whole words, with short model codes glued to their numbers.

    'Violão GD-20' and 'gd 20' both become ['violao', 'gd20'], so they match 'GD20'.
    """
    text = re.sub(r"\b([a-z]{1,3})[\s\-]+(?=\d)", r"\1", normalize(text))
    return re.findall(r"[a-z0-9]+", text)


def query_terms(text: str) -> list[str]:
    return [t for t in tokenize(text) if t not in STOPWORDS]


class StoreTools:
    def __init__(self, store: StoreData, now: Optional[Callable[[], datetime]] = None,
                 handoff_file: Path = HANDOFF_FILE):
        self.store = store
        self.now = now or (lambda: datetime.now(rules.STORE_TZ))
        self.handoff_file = handoff_file
        self._category_by_name = {normalize(c.name): c for c in store.categories.values()}

    # --- helpers --------------------------------------------------------------

    def _today(self) -> date:
        return self.now().astimezone(rules.STORE_TZ).date()

    def _haystack(self, p: Product) -> set[str]:
        category = self.store.categories.get(p.category_id)
        parts = [p.name, p.description, " ".join(map(str, p.specs.values())),
                 category.name if category else "", CATEGORY_KEYWORDS.get(p.category_id, "")]
        words = set(tokenize(" ".join(parts)))
        # Some descriptions mention a different brand than the product name
        # (data_quality.md, 1.7): only the name defines the brand.
        foreign = brands_in(p.description) - brands_in(p.name)
        return words - {w for b in foreign for w in tokenize(b)}

    def _summary(self, p: Product) -> dict:
        category = self.store.categories.get(p.category_id)
        quote = rules.price_quote(p, self.store)
        # Per-product installments, so the LLM never generalizes "12x" to cheap items.
        max_installments = rules.installment_options(quote["price"])[-1]
        return {
            "product_id": p.product_id,
            "name": p.name,
            "category": category.name if category else None,
            "availability": rules.availability(p),
            # Exact stock is internal: only a coarse level is exposed to the LLM.
            "last_units": rules.availability(p) == "in_stock" and p.stock_quantity <= LAST_UNITS,
            **quote,
            "max_installments": max_installments["installments"],
            "installment_value": max_installments["value"],
            # Ready-to-copy text, so the LLM never re-formats numbers.
            "display": {
                "price": rules.brl(quote["price"]),
                "list_price": rules.brl(quote["list_price"]),
                "pix_price": rules.brl(quote["pix_price"]),
                "installments": f"{max_installments['installments']}x de {rules.brl(max_installments['value'])}",
            },
        }

    def _alternatives(self, p: Product, limit: int = 3) -> list[dict]:
        """Available products in the same category, closest in price."""
        candidates = [
            other for other in self.store.products.values()
            if other.category_id == p.category_id and other.product_id != p.product_id
            and rules.availability(other) == "in_stock"
        ]
        candidates.sort(key=lambda o: abs(o.price_brl - p.price_brl))
        return [self._summary(o) for o in candidates[:limit]]

    def _rank(self, query: str, products: Optional[list[Product]] = None) -> tuple[list[Product], bool]:
        """Products with the highest number of matching query terms.

        Returns (best matches, whether they match *all* query terms).
        """
        terms = query_terms(query)
        scored = []
        for p in products if products is not None else self.store.products.values():
            haystack = self._haystack(p)
            score = sum(1 for t in terms if t in haystack)
            if score:
                scored.append((score, p))
        if not scored:
            return [], False
        scored.sort(key=lambda sp: (-sp[0], sp[1].price_brl))
        best = scored[0][0]
        return [p for score, p in scored if score == best], best == len(terms)

    # --- tools ------------------------------------------------------------------

    def search_products(self, query: str = "", category: Optional[str] = None,
                        min_price: Optional[float] = None, max_price: Optional[float] = None,
                        only_available: bool = True, limit: int = 20) -> dict:
        products = list(self.store.products.values())
        if category:
            cat = self._category_by_name.get(normalize(category))
            if cat is None:
                return {"error": f"Categoria desconhecida: {category}",
                        "valid_categories": [c.name for c in self.store.categories.values()]}
            products = [p for p in products if p.category_id == cat.category_id]

        # Rank after filtering by category, so matches in other categories
        # cannot push the relevant ones out.
        matched_all_terms = True
        if query_terms(query):
            products, matched_all_terms = self._rank(query, products)

        results = [self._summary(p) for p in products]
        if min_price is not None:
            results = [r for r in results if r["price"] >= min_price]
        if max_price is not None:
            results = [r for r in results if r["price"] <= max_price]

        unavailable = [r for r in results if r["availability"] != "in_stock"]
        if only_available:
            results = [r for r in results if r["availability"] == "in_stock"]
        results.sort(key=lambda r: r["price"])

        return {
            "total_found": len(results),
            # False means results only partially match the query (e.g. 'Yamaha
            # saxofone' -> Yamaha guitars): they are not what was asked for.
            "matched_all_terms": matched_all_terms,
            "products": results[:limit],
            "unavailable_matches": [
                {"name": r["name"], "availability": r["availability"]} for r in unavailable
            ] if only_available else [],
        }

    def get_product(self, product_id: Optional[int] = None, name: Optional[str] = None) -> dict:
        if product_id is not None:
            product = self.store.products.get(int(product_id))
            if product is None:
                return {"error": "Produto não encontrado no catálogo.", "query": product_id}
        else:
            # Never guess: a name lookup must identify exactly one product.
            matches, matched_all = self._rank(name or "")
            if not matches or not matched_all:
                return {
                    "error": "Nenhum produto do catálogo corresponde a todos os termos.",
                    "query": name,
                    "partial_matches_not_the_requested_product": [p.name for p in matches[:5]],
                }
            if len(matches) > 1:
                return {
                    "ambiguous": True,
                    "message": "Mais de um produto corresponde; pergunte ao cliente qual deles.",
                    "candidates": [self._summary(p) for p in matches[:6]],
                }
            product = matches[0]

        details = self._summary(product)
        details.update(description=product.description, specs=product.specs)
        if details["availability"] == "in_stock":
            details["payment"] = rules.payment_summary(details["price"], details["promotion"] is not None)
        else:
            details["alternatives"] = self._alternatives(product)
        return details

    def list_active_promotions(self) -> dict:
        promos = []
        for promo in self.store.promotions:
            product = self.store.products.get(promo.product_id)
            if promo.is_active and product and rules.availability(product) == "in_stock":
                promos.append(self._summary(product))
        return {"active_promotions": promos}

    def get_order_status(self, order_id: int, email_or_phone: str) -> dict:
        """Requires the email or phone registered for the order (LGPD)."""
        denied = {"verified": False,
                  "message": "Não foi possível localizar um pedido com esses dados. "
                             "Confira o número do pedido e o e-mail ou telefone do cadastro."}
        order = self.store.orders.get(int(order_id))
        if order is None:
            return denied
        customer = self.store.customers.get(order.customer_id)
        if customer is None:
            return denied

        contact = (email_or_phone or "").strip()
        given_digits = digits_only(contact)
        email_ok = normalize(contact) == normalize(customer.email)
        phone_ok = len(given_digits) >= 8 and digits_only(customer.phone).endswith(given_digits[-8:])
        if not (email_ok or phone_ok):
            return denied

        today = self._today()
        items = []
        for item in self.store.order_items.get(order.order_id, []):
            product = self.store.products.get(item.product_id)
            items.append({"product": product.name if product else f"produto {item.product_id}",
                          "quantity": item.quantity})

        result = {
            "verified": True,
            "customer_first_name": customer.name.split()[0],
            "order_id": order.order_id,
            "order_date": order.order_date.isoformat(),
            "status": order.status,
            "status_label": rules.ORDER_STATUS_LABELS[order.status],
            "total": order.total_brl,
            "payment_method": rules.payment_method_label(order.payment_method),
            "items": items,
            "tracking_code": order.tracking_code,
            "estimated_delivery": order.estimated_delivery.isoformat() if order.estimated_delivery else None,
            "notes": order.notes,
            "today": today.isoformat(),
        }
        if order.status == "shipped" and order.estimated_delivery and order.estimated_delivery < today:
            result["delayed"] = True
            result["days_late"] = (today - order.estimated_delivery).days
        if order.status in ("pending", "confirmed"):
            result["days_since_order"] = (today - order.order_date).days
        if order.status != "cancelled":
            result["returns"] = rules.return_eligibility(order, today)
        return result

    def simulate_payment(self, product_id: Optional[int] = None, amount: Optional[float] = None,
                         city: Optional[str] = None) -> dict:
        has_promotion = False
        if product_id is not None:
            product = self.store.products.get(int(product_id))
            if product is None:
                return {"error": "Produto não encontrado."}
            quote = rules.price_quote(product, self.store)
            amount, has_promotion = quote["price"], quote["promotion"] is not None
        if amount is None:
            return {"error": "Informe product_id ou amount."}

        result = rules.payment_summary(float(amount), has_promotion)
        if city:
            result["shipping"] = rules.shipping_quote(float(amount), city)
        return result

    def get_store_status(self) -> dict:
        return rules.store_status(self.now())

    def escalate_to_human(self, reason: str, summary: str, customer_contact: Optional[str] = None) -> dict:
        """Register a complaint or a case the agent cannot solve (manual 7.3)."""
        ticket = {
            "created_at": self.now().isoformat(timespec="seconds"),
            "reason": reason,
            "summary": summary,
            "customer_contact": customer_contact,
        }
        self.handoff_file.parent.mkdir(parents=True, exist_ok=True)
        with self.handoff_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ticket, ensure_ascii=False) + "\n")
        return {"registered": True, "response_time": "até 24 horas úteis"}

    # --- dispatch ----------------------------------------------------------------

    def execute(self, name: str, arguments: dict[str, Any]) -> dict:
        tool = getattr(self, name, None) if name in TOOL_NAMES else None
        if tool is None:
            return {"error": f"Ferramenta desconhecida: {name}"}
        try:
            return tool(**arguments)
        except (TypeError, ValueError) as exc:
            return {"error": f"Argumentos inválidos para {name}: {exc}"}


def _function(name: str, description: str, properties: dict, required: Optional[list] = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


def tool_schemas(store: StoreData) -> list[dict]:
    """OpenAI-compatible tool definitions (descriptions guide the LLM's tool choice)."""
    category_names = [c.name for c in store.categories.values()]
    return [
        _function(
            "search_products",
            "Search the instrument catalog. Use for questions about which products exist, "
            "options within a price range, or a brand/model. Prices returned already include "
            "active promotions. By default only in-stock products are returned; "
            "'unavailable_matches' lists matching products that cannot be sold now. "
            "'matched_all_terms: false' means results only partially match the query.",
            {
                "query": {"type": "string", "description": "Free text: brand, model or features (e.g. 'Yamaha nylon')."},
                "category": {"type": "string", "enum": category_names},
                "min_price": {"type": "number", "description": "Minimum price in BRL."},
                "max_price": {"type": "number", "description": "Maximum price in BRL."},
                "only_available": {"type": "boolean", "description": "Default true."},
                "limit": {"type": "integer", "description": "Max results, default 20."},
            },
        ),
        _function(
            "get_product",
            "Get full details of one product: price, promotion, PIX price, installments, "
            "availability, specs. If unavailable, returns similar alternatives. "
            "Always use before stating a product's price or availability. A name lookup never "
            "guesses: it returns 'ambiguous' with candidates, or an error if no product matches.",
            {
                "product_id": {"type": "integer"},
                "name": {"type": "string", "description": "Product name as said by the customer, if the id is unknown."},
            },
        ),
        _function(
            "list_active_promotions",
            "List products with a promotion active right now. Use when the customer asks about "
            "promotions, discounts or campaigns (e.g. Black Friday).",
            {},
        ),
        _function(
            "get_order_status",
            "Get the status of an order. Requires the order number AND the email or phone registered "
            "for it; ask the customer for both before calling. Also returns return/exchange eligibility.",
            {
                "order_id": {"type": "integer"},
                "email_or_phone": {"type": "string"},
            },
            ["order_id", "email_or_phone"],
        ),
        _function(
            "simulate_payment",
            "Compute payment options (PIX, debit, boleto, credit card installments) for a product or an "
            "amount, and optionally shipping for a destination city.",
            {
                "product_id": {"type": "integer"},
                "amount": {"type": "number", "description": "Amount in BRL, if not a single product."},
                "city": {"type": "string", "description": "Destination city for shipping."},
            },
        ),
        _function(
            "get_store_status",
            "Check whether the store is open right now and when it opens next.",
            {},
        ),
        _function(
            "escalate_to_human",
            "Register a complaint or a request the assistant cannot solve, so the human team "
            "contacts the customer within 24 business hours.",
            {
                "reason": {"type": "string", "enum": ["complaint", "delayed_order", "return_request",
                                                      "data_deletion", "other"]},
                "summary": {"type": "string", "description": "Short summary of the case, in Portuguese."},
                "customer_contact": {"type": "string", "description": "Customer's phone or email, if provided."},
            },
            ["reason", "summary"],
        ),
    ]


TOOL_NAMES = {
    "search_products", "get_product", "list_active_promotions", "get_order_status",
    "simulate_payment", "get_store_status", "escalate_to_human",
}

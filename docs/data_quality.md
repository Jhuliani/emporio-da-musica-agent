# Data Quality Report

The store provided six CSV tables and an internal policy manual (PDF). Before building the agent, all sources were cross-checked. This report lists every inconsistency found and the decision taken for each one.

**Guiding principle:** the agent must never give the customer wrong information about price, stock or deadlines (policy manual, section 7.1). When the data is ambiguous, the agent takes the **conservative** interpretation and, if needed, hands the case over to the human team. Inconsistencies are not silently fixed in the source files: the loader reports them (`python -m emporio.data`) so the store can correct them at the origin.

## 1. Catalog (products and categories)

| # | Finding | Decision |
|---|---|---|
| 1.1 | Product 96 (Giannini GF-3D) is `active` but has **stock 0**. | Treated as **temporarily unavailable**. The agent says so and suggests similar available products (manual 7.3). |
| 1.2 | Product 130 (Kala KA-ABP-CTG) is `coming_soon` but has **stock 2**, and appears in a **delivered** order (3) and a **pending** order (14). | **Status prevails over stock**: the product is presented as "coming soon", with no availability promise. Historical orders are reported as recorded. |
| 1.3 | Product 136 (Ibanez Bass 2X) is `discontinued` but has **stock 13**. | **Status prevails over stock**: not offered for sale; the agent offers equivalent models (manual 7.3). Possibly leftover stock the store should review. |
| 1.4 | Categories 6, 7 and 8 (woodwinds, brass, orchestral strings) have **no products**, while the manual says the store sells them and has "more than 300 instruments" (the CSV has 65). | The CSV is the source of truth. The agent **never invents products**; for these categories it says there are no items available in the system right now and suggests contacting the store. |
| 1.5 | Product specs mix languages and key formats (Portuguese for acoustic guitars, English for electric guitars, basses, drums and keyboards). | Kept as-is: they are passed to the LLM as structured data, which handles both languages. |
| 1.6 | Product IDs are not sequential (145 appears between 130 and 131). | No impact; IDs are only used as keys. |

## 2. Promotions

| # | Finding | Decision |
|---|---|---|
| 2.1 | Products 93, 96 and 99 have **two promotion records each** (all inactive). | Only promotions with `is_active = 1` are considered. If a product ever had more than one active promotion, the **highest discount** applies, since promotions are not cumulative (manual 6.2). |
| 2.2 | Only **4 promotions are active** (products 90, 94, 121, 127). The manual mentions campaigns such as Black Friday "15–30% on the whole catalog" (November), but all Black Friday records are inactive. | **The system prevails over the manual's general description**: the manual itself says to check whether a promotion is active in the system and never promise an expired discount (7.3). |
| 2.3 | The promotions table has no start/end dates. | `is_active` is the only validity signal. |
| 2.4 | Example from the challenge, "How much is the Takamine GD20?": product 95 has a 12% promotion that is **inactive**. | The agent quotes the regular price (R$ 2,199.00) and does not mention the discount. Covered by tests. |

## 3. Orders

| # | Finding | Decision |
|---|---|---|
| 3.1 | Order totals differ from the sum of items at current prices: order 3 (R$ 3,450 vs R$ 3,498) and order 20 (R$ 1,400 vs R$ 1,488). | Likely price changes or discounts at purchase time. The agent reports the **recorded order total** and never recalculates it. |
| 3.2 | Order 8 is `shipped` with estimated delivery on 2026-02-28 (already past). Orders 13–16 are `pending` since March 2026. | The agent reports the status honestly, acknowledges the delay and offers to forward the case to the team (complaint flow, 24 business hours — manual 7.3). |
| 3.3 | There is **no actual delivery date**, only `estimated_delivery`. The right of withdrawal counts 7 days **from receipt** (manual 4.1). | For delivered orders, `estimated_delivery` is used as a proxy for the receipt date. The agent states it is an estimate and, in borderline cases, refers the customer to the team for confirmation. |
| 3.4 | There is no sales channel field, but the right of withdrawal applies to **online purchases** (manual 4.1). | All orders in the system are assumed to be online (they all have shipping data). |
| 3.5 | Payment methods are codes (`pix`, `credit_6x`, `boleto`...). | Translated to readable text in the agent's answers. |

## 4. Customers and privacy

| # | Finding | Decision |
|---|---|---|
| 4.1 | Customers have no national ID (CPF) and the channel is a chat, so the customer's identity is unknown. | To protect personal data (LGPD, manual section 9), order details are only shown when the customer provides the **order number plus the email or phone** registered for it. |

## 5. Policy manual

The PDF was transcribed to [`data/policies.md`](../data/policies.md), which the agent reads. The decisions below are applied inline there, each one marked with "[Nota de consistência]".

| # | Finding | Decision |
|---|---|---|
| 5.1 | Two different WhatsApp numbers: **(67) 3341-4444** (cover and company data table, labeled "Phone / WhatsApp") and **(67) 3321-4500** (section 7). | (67) 3341-4444 is used: it appears twice, including the official company data table. |
| 5.2 | The email appears with an accent in section 1.2 (`contato@empóriodamusica.com.br`) and without it on the cover. | `contato@emporiodamusica.com.br` (no accent) is used: accented domains are unusual and the cover version is consistent with the brand. |
| 5.3 | Installment rules conflict: the payment table says "minimum installment R$ 100", while section 3.1 has tiers (up to 3x "no minimum, except below R$ 50"; 4–6x min. R$ 80; 7–12x min. R$ 100). The 3x rule contradicts itself. | Section 3.1 prevails (more specific). Interpretation: **1–3x: installments of at least R$ 50; 4–6x: at least R$ 80; 7–12x: at least R$ 100**. The table's R$ 100 is read as referring to the 12x limit. |
| 5.4 | Stores are closed on holidays, but there is no holiday list. | The agent applies the weekly schedule and mentions that the store is closed on holidays. |
| 5.5 | Shipping cost outside the Campo Grande metro area depends on ZIP code, weight and dimensions, which are not available. | The agent explains shipping options and estimated delivery times but does not quote a price; the cost is calculated at checkout. |

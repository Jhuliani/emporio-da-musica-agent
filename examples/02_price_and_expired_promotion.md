# Price check and an expired promotion

**Scenario:** The Takamine GD20 has a 12% promotion in the data, but it is inactive. The customer insists on the discount; the agent stays transparent (manual 7.3) and points to the promotions that are actually active.

_Generated with `gemini-3.5-flash-lite` on 2026-11-03 09:17 (Brasília time). Tool calls are shown as they happened; the conversation itself is in Portuguese, the store's language._

---

**👤 Cliente:** Quanto custa o Takamine GD20?

> 🔧 `get_product({"name": "Takamine GD20"})`

**🎸 Tom:**

O violão **Takamine GD20 Dreadnought Natural** custa **R$ 2.199,00** no valor de tabela. 

No PIX, com 5% de desconto, ele sai por **R$ 2.089,05**. Se preferir no cartão de crédito, dá para parcelar em até **12x sem juros de R$ 183,25**.

Precisa de mais alguma informação sobre ele? 🎸

---

**👤 Cliente:** Mas ele não estava com 12% de desconto?

> 🔧 `list_active_promotions({})`

**🎸 Tom:**

Verifiquei aqui no sistema e o Takamine GD20 não está com nenhuma promoção ativa no momento — o preço dele é R$ 2.199,00 mesmo (ou R$ 2.089,05 no PIX). 

De violões com desconto agora temos, por exemplo, o Crafter HT-100 Folk com 18% de off e o Taylor 110e com 8%. Quer dar uma olhada neles ou em outro modelo?

---

**👤 Cliente:** Poxa. E tem algum violão em promoção agora?

> 🔧 `list_active_promotions({})`

**🎸 Tom:**

Sim! Temos dois violões com desconto ativo no sistema agora:

- **Crafter HT-100 Folk Aço Natural**: de R$ 2.399,00 por **R$ 1.967,18** (18% de desconto) — parcelamento em até 12x sem juros de R$ 163,93.
- **Taylor 110e Dreadnought Natural**: de R$ 5.999,00 por **R$ 5.519,08** (8% de desconto) — parcelamento em até 12x sem juros de R$ 459,92.

*(Lembrando que para itens em promoção o desconto de 5% do PIX não acumula, ok?)*

Gostaria de saber mais detalhes sobre algum deles?

---

# Pricing Rules
# Applies to: commander/price_auditor.py, commander/budget_optimizer.py, all pricing logic

## Hard Rules — Never Violate

1. **Never estimate a card price from memory or training data.** Prices shift daily.
   A card that was $1 in training data may be $15 today. Always fetch live.

2. **Use TCGPlayer Market Price, not Low price.**
   "Low" = single damaged/played copy. Market = weighted average of recent sales.
   Low underestimates real purchase price by 20–40%.

3. **Always check all printings, not just the most recent.**
   Older reprints are frequently cheaper. A card like Necropotence has printings
   ranging from $8 to $40. Always find the cheapest NM-equivalent market price
   across all legal printings.

4. **Flag any card priced over $15 as "review required"** in output.
   Cards in this range can blow a $100 budget on their own.

5. **Maintain a per-card price log** in the output JSON.
   Never produce a final decklist without a line-item price breakdown.
   The $302 incident happened because there was no line-item audit.

## Preferred Data Sources (in order)
1. MTGGoldfish price page (scrape): `https://www.mtggoldfish.com/price/{Set}/{CardName}`
2. Scryfall prices endpoint: `https://api.scryfall.com/cards/named?exact={name}` → `.prices.usd`
3. TCGPlayer market price (requires API key): fallback only

## Scryfall Prices Note
Scryfall's `.prices.usd` field is the TCGPlayer low price for the specific printing,
updated daily. It is acceptable as a proxy when full TCGPlayer market data is
unavailable, but add a 30% buffer to estimated budget when using it.

## Budget Ceiling Enforcement
```python
# Hard stop logic — never exceed ceiling
running_total = 0
for card, price in sorted_cards_by_value:
    if running_total + price > budget_ceiling:
        find_cheaper_alternative(card)  # try lower-cost printing or substitute
    else:
        running_total += price
```

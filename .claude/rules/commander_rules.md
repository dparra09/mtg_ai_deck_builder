# Commander Rules Reference
# Applies to: commander/*.py — all Commander module files

## Core Format Rules
- 100-card singleton deck (99 cards + 1 Commander)
- Commander is a Legendary Creature (or has "can be your commander" text)
- All 99 cards must match the Commander's COLOR IDENTITY
- Color identity = all colored mana symbols in mana cost + oracle text
- Colorless cards ({C}, generic mana only) are ALWAYS legal
- Basic lands are exempt from singleton rule

## Color Identity Enforcement
```python
# A card is legal if its color_identity is a subset of commander_color_identity
def is_legal_in_deck(card_color_identity, commander_color_identity):
    return set(card_color_identity).issubset(set(commander_color_identity))

# Example: Mono-black commander (color_identity = ['B'])
# Legal: ['B'], [], ['C']  (black, colorless)
# ILLEGAL: ['B','R'], ['W'], ['U','B']
```

## Ban List Policy
- ALWAYS fetch ban list at runtime from Scryfall or mtgcommander.net
- NEVER hardcode a ban list — it changes with each Rules Committee announcement
- Scryfall query for legal Commander cards: `format:commander legal:commander`
- Known bans as of March 2026 (verify live before use):
  - Banned: Griselbrand, Hullbreacher, Leovold, Emissary of Trest,
    Flash, Jeweled Lotus, Mana Crypt, Dockside Extortionist
  - Recently UNBANNED: Biorhythm (Feb 2026), Coalition Victory, Sway of the Stars
  - ALWAYS verify — this list is stale the moment a new announcement drops

## Key Rules Edge Cases
- A card with a colored activated ability symbol in its rules text is NOT
  legal unless that color matches the commander's identity
  Example: Nightmare {X}{B}{B} has {B} in cost = black identity
- Hybrid mana symbols (e.g. {B/R}) make a card BOTH colors for identity
- Reminder text mana symbols DO count for color identity
- Land cards that can produce off-color mana: the colored symbol in the
  ability text counts for color identity
  Example: Exotic Orchard can produce any color but has no color identity symbols
  in its text → colorless identity → legal in any Commander deck

## Deck Validation Checklist
```
[ ] Exactly 100 cards total
[ ] Commander is Legendary Creature (or designated)
[ ] All 99 cards match commander color identity
[ ] No banned cards
[ ] No duplicate non-basic-land cards
[ ] Commander is not counted among the 99
```

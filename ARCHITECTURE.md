# Architecture Overview

## System Design Philosophy

This project is built around one hard lesson: **never estimate card prices from
memory or training data**. Every card price must be fetched live at the time of
deck construction. The $302 incident (a $100-target deck priced manually at over
3x budget) exists as a permanent reminder in every module's docstring.

---

## Data Flow

```
┌─────────────────────────────────────────────────────────┐
│                   USER INPUTS                           │
│  Commander name + Budget ceiling + (optional) existing  │
│  decklist for audit mode                                │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              SCRYFALL API (Live Data)                   │
│  commander/fetch_commander_cards.py                     │
│  • Resolve commander color identity                     │
│  • Fetch all legal cards in color identity              │
│  • Price data included per card                         │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              CONSTRAINT ENGINE                          │
│  commander/constraint_engine.py                         │
│  • Color identity filtering (hard filter)               │
│  • Ban list check (fetched live from Scryfall)          │
│  • Singleton validation                                 │
│  • Deck size validation                                 │
└──────────────────────────┬──────────────────────────────┘
                           │
                     ┌─────┴──────┐
                     │            │
                     ▼            ▼
          ┌──────────────┐  ┌──────────────────┐
          │  BUILD MODE  │  │   AUDIT MODE     │
          │              │  │                  │
          │ budget_       │  │ price_auditor.py │
          │ optimizer.py │  │ • Parse existing │
          │ • Score all  │  │   decklist       │
          │   cards      │  │ • Fetch live     │
          │ • Value =    │  │   prices for     │
          │   synergy/   │  │   every card     │
          │   price      │  │ • Find cheapest  │
          │ • Greedy     │  │   printing       │
          │   assembly   │  │ • Line-item      │
          │ • Hard budget│  │   breakdown      │
          │   ceiling    │  │ • Flag over-$15  │
          └──────┬───────┘  └────────┬─────────┘
                 │                   │
                 └─────────┬─────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    OUTPUTS                              │
│  • Decklist .txt (standard MTGGoldfish format)          │
│  • Price audit .json (line-item breakdown)              │
│  • Validation report (legality check results)           │
└─────────────────────────────────────────────────────────┘
```

---

## Module Responsibilities

### Existing Standard Pipeline (unchanged)
| File | Responsibility |
|---|---|
| `fetch_standard_legal_cards.py` | Scryfall Standard card pool → CSV |
| `current_standard_deck_list_scraper.py` | MTGGoldfish meta deck scraper |
| `deck_analysis.py` | Single-deck archetype detection |
| `analyze_meta_*.py` | Meta-wide analysis (3 approaches) |
| `consolidated_meta_analysis.py` | Multi-source reconciler |

### Commander Module (new)
| File | Responsibility |
|---|---|
| `commander/fetch_commander_cards.py` | Color-identity-filtered card pool |
| `commander/constraint_engine.py` | Format rule enforcement + validation |
| `commander/price_auditor.py` | **Live price lookup — the critical module** |
| `commander/budget_optimizer.py` | Value-scored greedy deck assembly |
| `commander/deck_builder.py` | Main CLI entry point |

---

## Key Dependencies

```
requests          # HTTP client for Scryfall, MTGGoldfish
pandas            # Card data processing and filtering
beautifulsoup4    # HTML scraping (MTGGoldfish deck lists)
scikit-learn      # Clustering in semantic analysis
sentence-transformers  # Text embeddings for semantic analysis
inflect           # NLP for deck name analysis
```

---

## Scryfall API Usage Notes

- Base URL: `https://api.scryfall.com`
- Rate limit: max 10 requests/second — we use 150ms delay
- No API key required for basic card data
- Price data: `card.prices.usd` = TCGPlayer non-foil market price
- Commander legality: `card.legalities.commander == 'legal'`
- Color identity: `card.color_identity` = list of color symbols
- Search operator `id<=WUBRG` returns cards whose identity is a subset

---

## Planned Enhancements (Roadmap)

1. **EDHREC synergy integration** — query EDHREC for commander-specific
   card recommendations, use as synergy_score signal in optimizer
2. **cEDH tier list integration** — score cards based on competitive viability
3. **Substitute recommender** — when a card is over budget, suggest
   the next-best card in the same role within budget
4. **Deck exporter** — export to Archidekt/Moxfield import format
5. **Price history tracking** — alert when a card's price has spiked
   significantly from its historical average
6. **Neural deck generator** — unsupervised model trained on EDHREC data
   to suggest non-obvious synergy packages

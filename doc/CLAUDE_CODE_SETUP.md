# Claude Code Setup Guide — MTG AI Deck Builder

## Prerequisites

1. **Claude Code installed** via npm:
   ```bash
   npm install -g @anthropic-ai/claude-code
   ```
2. **Anthropic API key** set in your environment:
   ```bash
   export ANTHROPIC_API_KEY="your-key-here"
   ```
3. **Python 3.10+** installed
4. **Git** for version control

---

## Quick Start

### 1. Clone / Initialize the repo
```bash
git clone https://github.com/georgejieh/mtg_ai_deck_builder.git
cd mtg_ai_deck_builder
```

### 2. Copy in the new Commander files
Place the following into the project root and `commander/` subdirectory
(all provided as part of this setup package):

**Root:**
- `CLAUDE.md` ← The persona + project memory file
- `requirements.txt` ← Updated with any new deps
- `.claude/rules/pricing.md`
- `.claude/rules/commander_rules.md`
- `.claude/rules/python_standards.md`

**`commander/` directory (create if needed):**
- `commander/__init__.py`
- `commander/fetch_commander_cards.py`
- `commander/constraint_engine.py`
- `commander/price_auditor.py`
- `commander/budget_optimizer.py`
- `commander/deck_builder.py`

**`docs/` directory:**
- `docs/ARCHITECTURE.md`
- `docs/madame_null_reference_list.txt`

### 3. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 4. Launch Claude Code
```bash
# From the project root — Claude will automatically read CLAUDE.md
claude
```

---

## Your First Commands in Claude Code

Once Claude Code is running in this project, CLAUDE.md loads automatically.
Claude already knows the MTG expert persona, the architecture, and the
$302 problem. Start immediately with the highest-priority task:

```
> Audit the Madame Null reference decklist for live pricing:
  python commander/price_auditor.py \
    --decklist docs/madame_null_reference_list.txt \
    --budget 100 \
    --output json_outputs/madame_null_price_audit.json
```

Or ask Claude Code directly:

```
> Run the price audit on docs/madame_null_reference_list.txt with a $100 budget
  and show me every card that's over $5 and what the cheapest legal printing is.
```

```
> The Cabal Coffers in the reference list is too expensive. Find me all
  black mana-doublers that are Commander-legal and under $3, sorted by
  how many Swamps they interact with.
```

```
> Build a new Madame Null deck from scratch using the budget optimizer
  and validate it passes all Commander format rules before outputting.
```

---

## Recommended Claude Code Session Flow

### Session 1 — Triage the $302 Problem
1. Run the price auditor on the reference list
2. Identify every card over $5
3. For each expensive card, find the cheapest legal printing
4. Find substitutes for cards with no affordable printing
5. Produce a revised list that actually hits $100

### Session 2 — Validate and Refine
1. Run constraint_engine on the revised list
2. Fix any color identity or legality violations
3. Evaluate synergy coverage (are all three combo lines intact?)
4. Final price audit to confirm budget compliance

### Session 3 — Harden the Pipeline
1. Write unit tests for constraint_engine validation logic
2. Test price_auditor against a known card to verify Scryfall integration
3. Add error handling for Scryfall API outages (cached fallback)

### Session 4 — Build Mode
1. Run fetch_commander_cards.py for Madame Null's identity
2. Run the full budget_optimizer pipeline
3. Compare optimizer output to the manually built deck
4. Identify gaps in the synergy scorer and improve it

---

## Memory Management Tips

Claude Code loads CLAUDE.md at the start of every session. The `.claude/rules/`
files are loaded on demand when relevant. You do NOT need to re-explain the
project, the persona, or the $302 problem at the start of each session.

**Use `/clear` between distinct tasks** to avoid context contamination.

**Tell Claude Code to remember things** during a session:
```
> Remember that Cabal Coffers MB2 white border is the target printing,
  not the original Onslaught printing.
```
Claude Code will write this to its auto-memory for future sessions.

**Reference docs directly** when you need deep context:
```
> Read docs/ARCHITECTURE.md and suggest the next logical module to build.
```

---

## Useful Slash Commands

| Command | What it does |
|---|---|
| `/init` | Regenerate CLAUDE.md from the current project structure |
| `/memory` | View and edit Claude Code's auto-memory |
| `/clear` | Clear context window (start fresh task) |
| `/add-dir ../path` | Add another directory to Claude's context |

---

## Troubleshooting

**"Card not found" errors in price_auditor:**
- Check that the card name exactly matches Scryfall's canonical name
- Split cards use `//` format: `Graven Lore` not `Graven Lore / Augur`
- Run: `python -c "import requests; r = requests.get('https://api.scryfall.com/cards/named?exact=YOUR+CARD'); print(r.json()['name'])"`

**Rate limit errors from Scryfall:**
- The delay settings (150ms) should prevent this
- If it happens: increase `REQUEST_DELAY` to 0.3 in the affected module
- Scryfall's actual limit is ~10 req/sec but they ask for 50–100ms

**Budget optimizer producing weird results:**
- The synergy scorer is heuristic-only in v1 — it doesn't know your specific commander's strategy
- Use BUILD mode as a starting point, then use AUDIT mode to validate manual adjustments
- EDHREC integration (Session 4+) will dramatically improve scorer quality

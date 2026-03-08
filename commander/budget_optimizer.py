"""
commander/budget_optimizer.py

Budget-aware deck assembly engine for Commander.
Scores cards by synergy-per-dollar and greedily assembles a decklist
that maximizes power within a hard budget ceiling.

Card value score = synergy_score / market_price
Assembly order = highest value_score first
Budget enforcement = hard stop, no overruns tolerated.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Slot Definitions
# ──────────────────────────────────────────────

@dataclass
class DeckSlot:
    """A role-based slot in a Commander deck."""
    role: str
    count: int
    min_count: int
    description: str


# Standard Commander deck slot template
# These targets are guidelines — optimizer will flex within ranges
COMMANDER_SLOT_TEMPLATE = [
    DeckSlot('ramp',        role='ramp',        count=10, min_count=8,
             description='Mana acceleration (rocks, dorks, land fetch)'),
    DeckSlot('draw',        role='draw',        count=10, min_count=8,
             description='Card draw and card advantage'),
    DeckSlot('removal',     role='removal',     count=10, min_count=8,
             description='Single-target removal and interaction'),
    DeckSlot('wipe',        role='wipe',        count=3,  min_count=2,
             description='Board wipes and mass removal'),
    DeckSlot('combo',       role='combo',       count=6,  min_count=0,
             description='Combo pieces and synergy enablers'),
    DeckSlot('threat',      role='threat',      count=12, min_count=8,
             description='Win conditions and high-impact threats'),
    DeckSlot('utility',     role='utility',     count=11, min_count=6,
             description='Flexible utility creatures and spells'),
    DeckSlot('land',        role='land',        count=37, min_count=35,
             description='Lands (including utility lands)'),
]


# ──────────────────────────────────────────────
# Card Scorer
# ──────────────────────────────────────────────

class CommanderCardScorer:
    """
    Scores cards for Commander suitability based on oracle text analysis.
    This is a heuristic scorer — EDHREC rank is used as the primary
    synergy signal when available; oracle text analysis fills the gaps.

    Score ranges from 0.0 to 10.0.
    Higher = better fit for Commander in general.
    Commander-specific synergy scoring requires the SynergyScorer module
    (not yet implemented — that requires EDHREC integration).
    """

    def score_card(self, card: pd.Series, commander_oracle: str = '') -> float:
        """
        Score a single card for Commander suitability.

        Args:
            card: A row from the Commander card DataFrame
            commander_oracle: The commander's oracle text (for synergy hints)

        Returns:
            Float score 0.0–10.0
        """
        score = 5.0  # Baseline

        oracle = str(card.get('oracle_text', '') or '').lower()
        type_line = str(card.get('type_line', '') or '')
        cmc = float(card.get('cmc', 4) or 4)
        edhrec_rank = card.get('edhrec_rank')

        # ── EDHREC rank boost (lower rank = more popular = more proven) ──
        if pd.notna(edhrec_rank) and edhrec_rank:
            rank = int(edhrec_rank)
            if rank <= 100:
                score += 3.0
            elif rank <= 500:
                score += 2.0
            elif rank <= 2000:
                score += 1.0
            elif rank >= 15000:
                score -= 1.0

        # ── Card advantage bonus ──────────────────────────────────────────
        if 'draw a card' in oracle:
            score += 0.5
        if 'draw two' in oracle or 'draw 2' in oracle:
            score += 1.0
        if 'whenever' in oracle and 'draw' in oracle:
            score += 0.75  # Repeatable draw

        # ── Removal bonus ─────────────────────────────────────────────────
        if 'destroy target' in oracle or 'exile target' in oracle:
            score += 0.5
        if 'destroy all' in oracle or 'exile all' in oracle:
            score += 1.0  # Board wipes are premium

        # ── Ramp bonus ────────────────────────────────────────────────────
        if 'add {' in oracle and cmc <= 3:
            score += 0.75
        if 'search your library' in oracle and 'land' in oracle:
            score += 0.5

        # ── ETB effects (synergize with flicker, recursion) ───────────────
        if 'enters' in oracle:
            score += 0.25

        # ── Recursion bonus ───────────────────────────────────────────────
        if 'return' in oracle and ('graveyard' in oracle or 'from your graveyard' in oracle):
            score += 0.5

        # ── CMC efficiency ────────────────────────────────────────────────
        if cmc <= 2:
            score += 0.5
        elif cmc >= 7:
            score -= 0.5  # High-CMC needs to justify itself

        # ── Penalty for situational cards ─────────────────────────────────
        if 'only if' in oracle or 'unless' in oracle:
            score -= 0.25

        # Clamp to valid range
        return round(max(0.0, min(10.0, score)), 2)

    def score_dataframe(
        self,
        df: pd.DataFrame,
        commander_oracle: str = ''
    ) -> pd.DataFrame:
        """Score all cards in a DataFrame. Adds 'synergy_score' column."""
        df = df.copy()
        df['synergy_score'] = df.apply(
            lambda row: self.score_card(row, commander_oracle), axis=1
        )
        return df


# ──────────────────────────────────────────────
# Budget Optimizer
# ──────────────────────────────────────────────

@dataclass
class AssembledDeck:
    """Result of the budget optimization pass."""
    commander_name: str
    budget_ceiling: float
    total_cost: float
    cards: list[dict] = field(default_factory=list)
    unmet_slots: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_within_budget(self) -> bool:
        return self.total_cost <= self.budget_ceiling

    @property
    def card_count(self) -> int:
        return sum(c['quantity'] for c in self.cards)


class BudgetOptimizer:
    """
    Greedily assembles a Commander deck within a budget ceiling.

    Algorithm:
    1. Score all legal cards by synergy_score / usd_price (value score)
    2. Tag each card with its primary role(s)
    3. Fill slots in priority order: ramp → draw → removal → threats → utility
    4. Land base filled last with fixed basic + utility land package
    5. Hard stop when budget ceiling is reached

    This is a greedy first-pass. The output should be reviewed by the
    MTG expert persona and refined for actual play patterns.
    """

    BASIC_LAND_FOR_IDENTITY = {
        'W': 'Plains', 'U': 'Island', 'B': 'Swamp', 'R': 'Mountain',
        'G': 'Forest', 'C': 'Wastes'
    }

    def __init__(self, budget_ceiling: float = 100.0):
        self.budget_ceiling = budget_ceiling
        self.scorer = CommanderCardScorer()

    def _tag_card_role(self, card: pd.Series) -> list[str]:
        """Assign role tags to a card based on oracle text and type."""
        roles = []
        oracle = str(card.get('oracle_text', '') or '').lower()
        type_line = str(card.get('type_line', '') or '')

        if 'Land' in type_line:
            roles.append('land')
            return roles  # Lands get only the land role

        # Ramp
        if (('add {' in oracle and float(card.get('cmc', 4) or 4) <= 4) or
                ('search your library' in oracle and 'land' in oracle) or
                'treasure' in oracle):
            roles.append('ramp')

        # Draw
        if 'draw' in oracle and ('card' in oracle or 'cards' in oracle):
            roles.append('draw')

        # Removal
        if (('destroy target' in oracle or 'exile target' in oracle) and
                'creature' in oracle):
            roles.append('removal')

        # Board wipes
        if 'destroy all' in oracle or 'exile all' in oracle:
            roles.append('wipe')

        # Recursion / combo / utility
        if 'return' in oracle and 'graveyard' in oracle:
            roles.append('combo')

        # Default to utility if no other role
        if not roles:
            roles.append('utility')

        return roles

    def _calculate_value_score(self, card: pd.Series) -> float:
        """
        Value score = synergy_score / price.
        Cards with no price get a low but non-zero score to allow selection.
        Cards priced at $0 get a bonus (bulk commons).
        """
        synergy = float(card.get('synergy_score', 5.0) or 5.0)
        price = card.get('usd_price')

        if price is None or price == 0.0:
            return synergy * 2.0  # Free cards are high value

        return synergy / price

    def optimize(
        self,
        card_pool: pd.DataFrame,
        commander_name: str,
        commander_oracle: str = '',
        slot_template: Optional[list[DeckSlot]] = None,
        basic_land_count: int = 28,
        utility_land_budget: int = 9,
    ) -> AssembledDeck:
        """
        Assemble the best deck possible within the budget ceiling.

        Args:
            card_pool: DataFrame of Commander-legal cards with price data
            commander_name: Name of the commander
            commander_oracle: Commander's oracle text (for synergy scoring)
            slot_template: Custom slot template (uses default if None)
            basic_land_count: Number of basic lands to include
            utility_land_budget: Budget slots for non-basic lands

        Returns:
            AssembledDeck with the selected cards and cost breakdown
        """
        slots = slot_template or COMMANDER_SLOT_TEMPLATE
        deck = AssembledDeck(
            commander_name=commander_name,
            budget_ceiling=self.budget_ceiling,
            total_cost=0.0
        )

        # Score all cards
        logger.info("Scoring card pool...")
        scored_pool = self.scorer.score_dataframe(card_pool, commander_oracle)
        scored_pool = scored_pool.copy()
        scored_pool['_roles'] = scored_pool.apply(self._tag_card_role, axis=1)
        scored_pool['_value_score'] = scored_pool.apply(self._calculate_value_score, axis=1)

        selected_names: set[str] = set()
        remaining_budget = self.budget_ceiling

        # ── Fill non-land slots ───────────────────────────────────────────
        for slot in slots:
            if slot.role == 'land':
                continue  # Lands handled separately

            logger.info(f"Filling slot: {slot.role} (target: {slot.count})")

            # Filter cards for this role, not already selected
            role_candidates = scored_pool[
                scored_pool['_roles'].apply(lambda roles: slot.role in roles) &
                ~scored_pool['full_name'].isin(selected_names) &
                scored_pool['is_land'].eq(False)
            ].copy()

            # Sort by value score descending
            role_candidates = role_candidates.sort_values('_value_score', ascending=False)

            filled = 0
            for _, card in role_candidates.iterrows():
                if filled >= slot.count:
                    break

                price = card.get('usd_price') or 0.0
                if remaining_budget - price < 0 and price > 0:
                    logger.warning(
                        f"  Budget tight — skipping {card['full_name']} (${price:.2f})"
                    )
                    continue

                selected_names.add(card['full_name'])
                remaining_budget -= price
                deck.total_cost += price
                deck.cards.append({
                    'card_name': card['full_name'],
                    'role': slot.role,
                    'quantity': 1,
                    'usd_price': round(price, 2),
                    'synergy_score': card.get('synergy_score', 0),
                    'value_score': round(card.get('_value_score', 0), 2),
                    'set': card.get('set', ''),
                })
                filled += 1

            if filled < slot.min_count:
                deck.warnings.append(
                    f"Could not fill minimum for slot '{slot.role}': "
                    f"got {filled}, needed {slot.min_count}"
                )

        # ── Fill utility lands (non-basics) ──────────────────────────────
        logger.info(f"Filling utility lands (budget: {utility_land_budget} slots)...")
        land_candidates = scored_pool[
            scored_pool['is_land'].eq(True) &
            ~scored_pool['full_name'].isin(selected_names)
        ].sort_values('_value_score', ascending=False)

        utility_filled = 0
        for _, card in land_candidates.iterrows():
            if utility_filled >= utility_land_budget:
                break

            # Skip pure basics here — we'll add them as a fixed package
            if card['full_name'] in set(self.BASIC_LAND_FOR_IDENTITY.values()):
                continue

            price = card.get('usd_price') or 0.0
            if remaining_budget - price < 0 and price > 0:
                continue

            selected_names.add(card['full_name'])
            remaining_budget -= price
            deck.total_cost += price
            deck.cards.append({
                'card_name': card['full_name'],
                'role': 'land',
                'quantity': 1,
                'usd_price': round(price, 2),
                'synergy_score': card.get('synergy_score', 0),
                'value_score': round(card.get('_value_score', 0), 2),
                'set': card.get('set', ''),
            })
            utility_filled += 1

        # ── Fill basic lands ──────────────────────────────────────────────
        # Determine which basic land to use based on first color in pool
        # (mono-color commanders get all of one basic)
        sample_cards = scored_pool[scored_pool['is_land'].eq(False)].head(1)
        if not sample_cards.empty:
            identity = sample_cards.iloc[0].get('color_identity', ['B'])
            if isinstance(identity, list) and identity:
                primary_color = identity[0]
            else:
                primary_color = 'B'
        else:
            primary_color = 'B'

        basic_name = self.BASIC_LAND_FOR_IDENTITY.get(primary_color, 'Swamp')
        deck.cards.append({
            'card_name': basic_name,
            'role': 'land',
            'quantity': basic_land_count,
            'usd_price': 0.0,
            'synergy_score': 1.0,
            'value_score': 999.0,
            'set': 'basic',
        })

        deck.total_cost = round(deck.total_cost, 2)
        logger.info(
            f"Assembly complete: {deck.card_count} cards, "
            f"${deck.total_cost:.2f} / ${deck.budget_ceiling:.2f}"
        )
        return deck

    def print_deck(self, deck: AssembledDeck) -> None:
        """Print the assembled deck in a readable format."""
        print(f"\n{'='*60}")
        print(f"  ASSEMBLED DECK: {deck.commander_name}")
        print(f"  Budget: ${deck.total_cost:.2f} / ${deck.budget_ceiling:.2f}")
        print(f"  Cards: {deck.card_count}")
        print(f"{'='*60}\n")

        current_role = None
        for card in sorted(deck.cards, key=lambda c: (c['role'], -c['value_score'])):
            if card['role'] != current_role:
                current_role = card['role']
                print(f"\n  — {current_role.upper()} —")
            qty = card['quantity']
            name = card['card_name']
            price = f"${card['usd_price']:.2f}" if card['usd_price'] else "free"
            print(f"  {qty}x {name:<45} {price}")

        if deck.warnings:
            print(f"\n  ⚠  WARNINGS:")
            for w in deck.warnings:
                print(f"     {w}")

        status = "✓ WITHIN BUDGET" if deck.is_within_budget else "✗ OVER BUDGET"
        print(f"\n  {status}")
        print(f"{'='*60}\n")

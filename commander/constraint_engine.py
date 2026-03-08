"""
commander/constraint_engine.py

Hard rule enforcement for Commander deckbuilding.
Validates color identity, singleton constraint, ban list compliance,
and deck size requirements.

Never hardcode the ban list — fetch it live from Scryfall.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional
import requests

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a deck validation check."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str):
        self.warnings.append(msg)


@dataclass
class CommanderProfile:
    """Core data about a commander card."""
    name: str
    color_identity: list[str]   # e.g. ['B'] or ['U', 'R'] or []
    is_legendary: bool
    is_legal_commander: bool
    scryfall_id: str


class CommanderConstraintEngine:
    """
    Enforces all Commander format rules against a proposed decklist.

    Rules enforced:
    - Exactly 100 cards (99 + commander)
    - Commander must be a Legendary Creature (or have designator text)
    - All 99 cards must match commander color identity
    - No banned cards (fetched live from Scryfall)
    - Singleton constraint (one copy of each non-basic land)
    """

    BASIC_LANDS = {
        'Plains', 'Island', 'Swamp', 'Mountain', 'Forest', 'Wastes',
        'Snow-Covered Plains', 'Snow-Covered Island', 'Snow-Covered Swamp',
        'Snow-Covered Mountain', 'Snow-Covered Forest'
    }
    REQUEST_DELAY = 0.15

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'MTGAIDeckBuilder/2.0 (Commander Constraint Engine)',
            'Accept': 'application/json'
        })
        self._ban_list_cache: Optional[set[str]] = None
        self._card_cache: dict[str, dict] = {}

    def _scryfall_get(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        time.sleep(self.REQUEST_DELAY)
        try:
            response = self.session.get(
                f"https://api.scryfall.com/{endpoint}",
                params=params,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Scryfall request failed ({endpoint}): {e}")
            return None

    def get_commander_profile(self, commander_name: str) -> Optional[CommanderProfile]:
        """
        Fetch commander card data from Scryfall.
        Validates that the card is a legal Commander.
        """
        logger.info(f"Fetching commander profile: {commander_name}")
        data = self._scryfall_get('cards/named', {'exact': commander_name})
        if not data:
            logger.error(f"Could not find commander: {commander_name}")
            return None

        type_line = data.get('type_line', '')
        oracle_text = data.get('oracle_text', '')
        legalities = data.get('legalities', {})

        is_legendary = 'Legendary' in type_line
        is_creature = 'Creature' in type_line
        has_designator = 'can be your commander' in oracle_text.lower()

        is_legal_commander = (
            legalities.get('commander') == 'legal' and
            (is_legendary and is_creature or has_designator)
        )

        return CommanderProfile(
            name=data.get('name', commander_name),
            color_identity=data.get('color_identity', []),
            is_legendary=is_legendary,
            is_legal_commander=is_legal_commander,
            scryfall_id=data.get('id', '')
        )

    def fetch_ban_list(self) -> set[str]:
        """
        Fetch the current Commander ban list from Scryfall.
        Returns a set of banned card names (lowercase for comparison).

        Uses Scryfall's legality data — searches for cards that are banned
        in Commander format.
        """
        if self._ban_list_cache is not None:
            return self._ban_list_cache

        logger.info("Fetching Commander ban list from Scryfall...")
        banned = set()
        params = {
            'q': 'banned:commander',
            'unique': 'cards',
        }

        data = self._scryfall_get('cards/search', params)
        if not data:
            logger.warning("Could not fetch ban list — proceeding without ban check")
            return banned

        for card in data.get('data', []):
            banned.add(card['name'].lower())

        # Handle pagination
        while data.get('has_more') and data.get('next_page'):
            time.sleep(self.REQUEST_DELAY)
            try:
                response = self.session.get(data['next_page'], timeout=10)
                response.raise_for_status()
                data = response.json()
                for card in data.get('data', []):
                    banned.add(card['name'].lower())
            except Exception as e:
                logger.error(f"Ban list pagination error: {e}")
                break

        logger.info(f"Loaded {len(banned)} banned Commander cards")
        self._ban_list_cache = banned
        return banned

    def get_card_color_identity(self, card_name: str) -> Optional[list[str]]:
        """Fetch the color identity of a single card from Scryfall."""
        if card_name in self._card_cache:
            return self._card_cache[card_name].get('color_identity')

        data = self._scryfall_get('cards/named', {'exact': card_name})
        if data:
            self._card_cache[card_name] = data
            return data.get('color_identity', [])
        return None

    def validate_deck(
        self,
        commander_name: str,
        decklist: list[tuple[int, str]]  # (quantity, card_name)
    ) -> ValidationResult:
        """
        Full validation of a Commander deck.

        Args:
            commander_name: The name of the commander card
            decklist: List of (quantity, card_name) tuples for the 99

        Returns:
            ValidationResult with all errors and warnings
        """
        result = ValidationResult(is_valid=True)

        # ── 1. Validate commander ──────────────────────
        commander = self.get_commander_profile(commander_name)
        if not commander:
            result.add_error(f"Commander '{commander_name}' not found in Scryfall")
            return result

        if not commander.is_legal_commander:
            result.add_error(
                f"'{commander_name}' is not a legal Commander "
                f"(must be Legendary Creature or have designator text)"
            )

        logger.info(
            f"Commander: {commander.name} | "
            f"Color identity: {commander.color_identity or ['Colorless']}"
        )

        # ── 2. Validate deck size ──────────────────────
        total_cards = sum(q for q, _ in decklist)
        if total_cards != 99:
            result.add_error(
                f"Deck has {total_cards} cards — Commander format requires exactly 99 "
                f"(plus the commander for 100 total)"
            )

        # ── 3. Check for duplicates (singleton) ───────
        card_counts: dict[str, int] = {}
        for quantity, name in decklist:
            card_counts[name] = card_counts.get(name, 0) + quantity

        for name, count in card_counts.items():
            if count > 1 and name not in self.BASIC_LANDS:
                result.add_error(
                    f"Singleton violation: '{name}' appears {count} times "
                    f"(only basic lands may repeat)"
                )

        # ── 4. Check for commander in the 99 ──────────
        for _, name in decklist:
            if name.lower() == commander_name.lower():
                result.add_error(
                    f"Commander '{commander_name}' appears in the 99 — "
                    f"the commander is separate from the deck"
                )

        # ── 5. Fetch and check ban list ────────────────
        ban_list = self.fetch_ban_list()
        for _, name in decklist:
            if name.lower() in ban_list:
                result.add_error(f"BANNED card in deck: '{name}'")

        # ── 6. Check color identity ────────────────────
        commander_identity = set(commander.color_identity)

        for _, name in decklist:
            if name in self.BASIC_LANDS:
                continue

            card_identity = self.get_card_color_identity(name)
            if card_identity is None:
                result.add_warning(f"Could not verify color identity for: '{name}'")
                continue

            card_identity_set = set(card_identity)
            if not card_identity_set.issubset(commander_identity):
                illegal_colors = card_identity_set - commander_identity
                result.add_error(
                    f"Color identity violation: '{name}' has {illegal_colors} "
                    f"which is outside commander identity {commander_identity or {'Colorless'}}"
                )

        return result

    def filter_card_pool_by_identity(
        self,
        cards: list[dict],
        commander_color_identity: list[str]
    ) -> list[dict]:
        """
        Filter a list of Scryfall card objects to those legal in the commander's
        color identity.

        Args:
            cards: List of Scryfall card data dicts (must have 'color_identity' key)
            commander_color_identity: The commander's color identity list

        Returns:
            Filtered list of cards legal in the deck
        """
        identity_set = set(commander_color_identity)
        legal = []
        for card in cards:
            card_identity = set(card.get('color_identity', []))
            if card_identity.issubset(identity_set):
                legal.append(card)
        return legal


# ──────────────────────────────────────────────
# CLI Entry Point
# ──────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    import sys
    sys.path.insert(0, '..')
    from commander.price_auditor import parse_decklist

    parser = argparse.ArgumentParser(
        description='Validate a Commander deck for format legality.'
    )
    parser.add_argument('--commander', type=str, required=True,
                        help='Exact commander card name')
    parser.add_argument('--decklist', type=str, required=True,
                        help='Path to 99-card decklist .txt file')
    args = parser.parse_args()

    cards = parse_decklist(args.decklist)
    engine = CommanderConstraintEngine()
    result = engine.validate_deck(args.commander, cards)

    print(f"\n{'='*50}")
    print(f"  VALIDATION: {args.commander}")
    print(f"{'='*50}")

    if result.is_valid:
        print("  ✓ Deck is format-legal")
    else:
        print(f"  ✗ {len(result.errors)} error(s) found")
        for err in result.errors:
            print(f"    ERROR: {err}")

    if result.warnings:
        print(f"\n  {len(result.warnings)} warning(s):")
        for w in result.warnings:
            print(f"    WARNING: {w}")

    print(f"{'='*50}\n")
    sys.exit(0 if result.is_valid else 1)

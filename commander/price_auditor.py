"""
commander/price_auditor.py

Real-time price auditor for Commander decklists.
Fetches live prices from Scryfall (TCGPlayer data) for each card in a decklist,
finds the cheapest legal printing, and produces a line-item budget report.

This module was built to solve the core problem: manually estimated prices
caused a $100-target deck to ring up at $302. Never estimate prices. Fetch live.

Usage:
    python commander/price_auditor.py --decklist my_deck.txt --budget 100
    python commander/price_auditor.py --decklist my_deck.txt --budget 100 --output audited.json
"""

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Data Classes
# ──────────────────────────────────────────────

@dataclass
class PrintingPrice:
    """Price data for a single printing of a card."""
    set_code: str
    set_name: str
    collector_number: str
    usd_price: Optional[float]       # TCGPlayer market via Scryfall
    usd_foil_price: Optional[float]
    scryfall_id: str
    is_legal_commander: bool = True


@dataclass
class CardPriceResult:
    """Full price audit result for a single card."""
    card_name: str
    quantity: int
    cheapest_printing: Optional[PrintingPrice]
    all_printings: list[PrintingPrice] = field(default_factory=list)
    review_required: bool = False    # True if cheapest price > $15
    error: Optional[str] = None

    @property
    def line_total(self) -> float:
        if self.cheapest_printing and self.cheapest_printing.usd_price:
            return self.cheapest_printing.usd_price * self.quantity
        return 0.0

    @property
    def price_display(self) -> str:
        if self.error:
            return f"ERROR: {self.error}"
        if not self.cheapest_printing or self.cheapest_printing.usd_price is None:
            return "PRICE NOT FOUND"
        return f"${self.cheapest_printing.usd_price:.2f} ({self.cheapest_printing.set_code.upper()})"


@dataclass
class DeckAuditReport:
    """Full audit report for an entire decklist."""
    total_cards: int
    total_price: float
    budget_ceiling: float
    over_budget: bool
    overage: float
    cards: list[CardPriceResult] = field(default_factory=list)
    review_required_cards: list[str] = field(default_factory=list)
    price_not_found: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────
# Scryfall Client
# ──────────────────────────────────────────────

class ScryfallPriceClient:
    """
    Fetches card price data from Scryfall API.
    Scryfall prices are sourced from TCGPlayer and updated daily.
    Rate limit: 10 requests/second max → we use 150ms delay to be safe.
    """

    BASE_URL = "https://api.scryfall.com"
    REQUEST_DELAY = 0.15  # 150ms between requests

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'MTGAIDeckBuilder/2.0 (Commander Price Auditor)',
            'Accept': 'application/json'
        })
        self._cache: dict[str, list[PrintingPrice]] = {}

    def _get(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        """Make a rate-limited GET request to Scryfall."""
        time.sleep(self.REQUEST_DELAY)
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching {url}")
            return None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"Card not found: {url}")
            else:
                logger.error(f"HTTP {e.response.status_code} for {url}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            return None

    def get_all_printings(self, card_name: str) -> list[PrintingPrice]:
        """
        Fetch all printings of a card and their prices.
        Uses Scryfall's /cards/search with unique=prints to get every printing.
        Filters to Commander-legal printings only.
        """
        if card_name in self._cache:
            return self._cache[card_name]

        logger.info(f"Fetching printings for: {card_name}")

        # Search for all printings
        params = {
            'q': f'!"{card_name}" game:paper',
            'unique': 'prints',
            'order': 'usd',
            'dir': 'asc'  # cheapest first
        }

        data = self._get('cards/search', params)
        if not data or 'data' not in data:
            logger.warning(f"No printings found for: {card_name}")
            return []

        printings = []
        for card_data in data['data']:
            # Check Commander legality
            legalities = card_data.get('legalities', {})
            is_legal = legalities.get('commander') == 'legal'

            # Extract prices
            prices = card_data.get('prices', {})
            usd_str = prices.get('usd')
            usd_foil_str = prices.get('usd_foil')

            usd_price = float(usd_str) if usd_str else None
            usd_foil_price = float(usd_foil_str) if usd_foil_str else None

            printing = PrintingPrice(
                set_code=card_data.get('set', '???'),
                set_name=card_data.get('set_name', 'Unknown Set'),
                collector_number=card_data.get('collector_number', ''),
                usd_price=usd_price,
                usd_foil_price=usd_foil_price,
                scryfall_id=card_data.get('id', ''),
                is_legal_commander=is_legal
            )
            printings.append(printing)

        # Handle pagination
        while data.get('has_more') and data.get('next_page'):
            time.sleep(self.REQUEST_DELAY)
            try:
                response = self.session.get(data['next_page'], timeout=10)
                response.raise_for_status()
                data = response.json()
                for card_data in data.get('data', []):
                    legalities = card_data.get('legalities', {})
                    is_legal = legalities.get('commander') == 'legal'
                    prices = card_data.get('prices', {})
                    usd_str = prices.get('usd')
                    usd_foil_str = prices.get('usd_foil')
                    printing = PrintingPrice(
                        set_code=card_data.get('set', '???'),
                        set_name=card_data.get('set_name', 'Unknown Set'),
                        collector_number=card_data.get('collector_number', ''),
                        usd_price=float(usd_str) if usd_str else None,
                        usd_foil_price=float(usd_foil_str) if usd_foil_str else None,
                        scryfall_id=card_data.get('id', ''),
                        is_legal_commander=legalities.get('commander') == 'legal'
                    )
                    printings.append(printing)
            except Exception as e:
                logger.error(f"Pagination error for {card_name}: {e}")
                break

        self._cache[card_name] = printings
        logger.info(f"  Found {len(printings)} printings for {card_name}")
        return printings

    def get_cheapest_printing(self, card_name: str) -> CardPriceResult:
        """
        Find the cheapest legal NM Commander printing of a card.
        Returns a CardPriceResult with full price breakdown.
        """
        printings = self.get_all_printings(card_name)

        if not printings:
            return CardPriceResult(
                card_name=card_name,
                quantity=1,
                cheapest_printing=None,
                error="Card not found in Scryfall"
            )

        # Filter to legal printings with a price
        legal_priced = [
            p for p in printings
            if p.is_legal_commander and p.usd_price is not None
        ]

        if not legal_priced:
            # Maybe the card is banned or has no paper price
            legal_only = [p for p in printings if p.is_legal_commander]
            if not legal_only:
                return CardPriceResult(
                    card_name=card_name,
                    quantity=1,
                    cheapest_printing=None,
                    all_printings=printings,
                    error="No Commander-legal printing found (card may be banned)"
                )
            return CardPriceResult(
                card_name=card_name,
                quantity=1,
                cheapest_printing=None,
                all_printings=printings,
                error="Legal printing exists but no price data available"
            )

        # Sort by price ascending, pick cheapest
        legal_priced.sort(key=lambda p: p.usd_price)
        cheapest = legal_priced[0]

        result = CardPriceResult(
            card_name=card_name,
            quantity=1,
            cheapest_printing=cheapest,
            all_printings=printings,
            review_required=(cheapest.usd_price > 15.0)
        )

        return result


# ──────────────────────────────────────────────
# Decklist Parser
# ──────────────────────────────────────────────

def parse_decklist(file_path: str) -> list[tuple[int, str]]:
    """
    Parse a decklist text file into (quantity, card_name) tuples.

    Supports formats:
        4 Lightning Bolt
        1x Swamp
        Swamp (no quantity = assumed 1)
        // Comment lines are skipped
        Blank lines between mainboard/sideboard are skipped
    """
    cards = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()

            # Skip comments and blank lines
            if not line or line.startswith('//') or line.startswith('#'):
                continue

            # Parse "N CardName" or "NxCardName" or just "CardName"
            import re
            match = re.match(r'^(\d+)[x\s]+(.+)$', line)
            if match:
                quantity = int(match.group(1))
                name = match.group(2).strip()
            else:
                quantity = 1
                name = line

            # Strip set annotations like (M21) #123
            name = re.sub(r'\s*\([A-Z0-9]+\)\s*#?\d*\s*$', '', name).strip()

            if name:
                cards.append((quantity, name))

    return cards


# ──────────────────────────────────────────────
# Price Auditor
# ──────────────────────────────────────────────

class CommanderPriceAuditor:
    """
    Full price audit engine for Commander decklists.

    Fetches live pricing for every card, finds cheapest legal printing,
    produces a line-item report, and flags budget overages.
    """

    REVIEW_THRESHOLD = 15.00  # Flag cards above this price for manual review

    def __init__(self, budget_ceiling: float = 100.0):
        self.budget_ceiling = budget_ceiling
        self.client = ScryfallPriceClient()

    def audit_decklist(
        self,
        cards: list[tuple[int, str]],
        skip_basics: bool = True
    ) -> DeckAuditReport:
        """
        Audit every card in the decklist and produce a full price report.

        Args:
            cards: List of (quantity, card_name) tuples
            skip_basics: If True, skip basic lands (they're free / you own them)

        Returns:
            DeckAuditReport with line-item prices and budget analysis
        """
        BASIC_LANDS = {
            'Plains', 'Island', 'Swamp', 'Mountain', 'Forest',
            'Wastes', 'Snow-Covered Plains', 'Snow-Covered Island',
            'Snow-Covered Swamp', 'Snow-Covered Mountain', 'Snow-Covered Forest'
        }

        results = []
        total_price = 0.0

        for quantity, name in cards:
            if skip_basics and name in BASIC_LANDS:
                logger.info(f"Skipping basic land: {name}")
                results.append(CardPriceResult(
                    card_name=name,
                    quantity=quantity,
                    cheapest_printing=None,
                    error="Basic land — price skipped"
                ))
                continue

            result = self.client.get_cheapest_printing(name)
            result.quantity = quantity
            results.append(result)

            if result.cheapest_printing and result.cheapest_printing.usd_price:
                line_cost = result.cheapest_printing.usd_price * quantity
                total_price += line_cost
                logger.info(
                    f"  {name}: {result.price_display} "
                    f"(line total: ${line_cost:.2f})"
                )
            else:
                logger.warning(f"  {name}: {result.price_display}")

        over_budget = total_price > self.budget_ceiling
        overage = max(0.0, total_price - self.budget_ceiling)

        review_cards = [r.card_name for r in results if r.review_required]
        not_found = [r.card_name for r in results if r.error and 'Basic land' not in (r.error or '')]

        return DeckAuditReport(
            total_cards=sum(q for q, _ in cards),
            total_price=round(total_price, 2),
            budget_ceiling=self.budget_ceiling,
            over_budget=over_budget,
            overage=round(overage, 2),
            cards=results,
            review_required_cards=review_cards,
            price_not_found=not_found
        )

    def print_report(self, report: DeckAuditReport) -> None:
        """Print a formatted price report to stdout."""
        print("\n" + "=" * 65)
        print("  COMMANDER DECK PRICE AUDIT")
        print("=" * 65)
        print(f"  Total cards:    {report.total_cards}")
        print(f"  Budget ceiling: ${report.budget_ceiling:.2f}")
        print(f"  Actual cost:    ${report.total_price:.2f}")

        if report.over_budget:
            print(f"  ⚠  OVER BUDGET by ${report.overage:.2f}")
        else:
            remaining = report.budget_ceiling - report.total_price
            print(f"  ✓  Under budget — ${remaining:.2f} remaining")

        print("\n" + "-" * 65)
        print(f"  {'CARD':<40} {'PRICE':<15} {'LINE TOTAL'}")
        print("-" * 65)

        for r in report.cards:
            if r.error and 'Basic land' in (r.error or ''):
                continue
            flag = " ⚠" if r.review_required else ""
            line_total = f"${r.line_total:.2f}" if r.line_total > 0 else "—"
            print(f"  {r.card_name:<40} {r.price_display:<15} {line_total}{flag}")

        if report.review_required_cards:
            print("\n" + "-" * 65)
            print("  ⚠  REVIEW REQUIRED (cards over $15):")
            for name in report.review_required_cards:
                print(f"     • {name}")

        if report.price_not_found:
            print("\n  ✗  PRICE NOT FOUND:")
            for name in report.price_not_found:
                print(f"     • {name}")

        print("=" * 65 + "\n")

    def save_report(self, report: DeckAuditReport, output_path: str) -> None:
        """Save the full audit report as JSON."""
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)

        # Convert dataclasses to dicts for JSON serialization
        report_dict = {
            'total_cards': report.total_cards,
            'total_price': report.total_price,
            'budget_ceiling': report.budget_ceiling,
            'over_budget': report.over_budget,
            'overage': report.overage,
            'review_required_cards': report.review_required_cards,
            'price_not_found': report.price_not_found,
            'cards': []
        }

        for r in report.cards:
            card_dict = {
                'card_name': r.card_name,
                'quantity': r.quantity,
                'line_total': r.line_total,
                'review_required': r.review_required,
                'error': r.error,
                'cheapest_printing': None,
                'printings_checked': len(r.all_printings)
            }
            if r.cheapest_printing:
                card_dict['cheapest_printing'] = {
                    'set_code': r.cheapest_printing.set_code,
                    'set_name': r.cheapest_printing.set_name,
                    'usd_price': r.cheapest_printing.usd_price,
                    'scryfall_id': r.cheapest_printing.scryfall_id
                }
            report_dict['cards'].append(card_dict)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report_dict, f, indent=2)

        logger.info(f"Report saved to: {output_path}")


# ──────────────────────────────────────────────
# CLI Entry Point
# ──────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description='Audit the price of a Commander decklist against a budget ceiling.'
    )
    parser.add_argument(
        '--decklist',
        type=str,
        required=True,
        help='Path to the decklist .txt file'
    )
    parser.add_argument(
        '--budget',
        type=float,
        default=100.0,
        help='Budget ceiling in USD (default: 100.0)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Path to save JSON audit report (optional)'
    )
    parser.add_argument(
        '--include-basics',
        action='store_true',
        help='Include basic land prices in the total (default: skip basics)'
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()

    print(f"\nLoading decklist from: {args.decklist}")
    cards = parse_decklist(args.decklist)
    print(f"Parsed {len(cards)} card entries. Starting price audit...\n")

    auditor = CommanderPriceAuditor(budget_ceiling=args.budget)
    report = auditor.audit_decklist(cards, skip_basics=not args.include_basics)
    auditor.print_report(report)

    if args.output:
        auditor.save_report(report, args.output)
        print(f"Full report saved to: {args.output}")

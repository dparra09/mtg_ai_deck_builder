"""
commander/deck_builder.py

Main CLI entry point for the Commander deck building pipeline.
Ties together: card fetching → constraint validation → price auditing →
budget-optimized assembly → output.

Usage:
    # Build a new deck from scratch
    python commander/deck_builder.py \\
        --commander "Madame Null, Power Broker" \\
        --budget 100 \\
        --output commander_decks/madame_null.txt

    # Audit an existing decklist
    python commander/deck_builder.py \\
        --audit commander_decks/madame_null.txt \\
        --commander "Madame Null, Power Broker" \\
        --budget 100
"""

import argparse
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from commander.fetch_commander_cards import CommanderCardFetcher
from commander.constraint_engine import CommanderConstraintEngine
from commander.price_auditor import CommanderPriceAuditor, parse_decklist
from commander.budget_optimizer import BudgetOptimizer


def audit_existing_deck(
    decklist_path: str,
    commander_name: str,
    budget: float
) -> None:
    """
    Audit mode: validate and price-check an existing decklist.
    This is the primary tool for catching the $302 problem before purchase.
    """
    print(f"\n🔍  AUDIT MODE")
    print(f"    Decklist: {decklist_path}")
    print(f"    Commander: {commander_name}")
    print(f"    Budget ceiling: ${budget:.2f}\n")

    # Parse decklist
    cards = parse_decklist(decklist_path)
    print(f"Parsed {len(cards)} card entries from decklist.\n")

    # Validate format legality
    print("Step 1/2: Validating format legality...")
    engine = CommanderConstraintEngine()
    validation = engine.validate_deck(commander_name, cards)

    if validation.is_valid:
        print("  ✓ Deck passes all format legality checks\n")
    else:
        print(f"  ✗ {len(validation.errors)} legality error(s) found:")
        for err in validation.errors:
            print(f"    • {err}")
        print()

    if validation.warnings:
        for w in validation.warnings:
            print(f"  ⚠ {w}")
        print()

    # Price audit
    print("Step 2/2: Running live price audit...")
    print("  (Fetching current prices from Scryfall — this may take a few minutes)\n")

    auditor = CommanderPriceAuditor(budget_ceiling=budget)
    report = auditor.audit_decklist(cards)
    auditor.print_report(report)

    # Save JSON report
    report_path = decklist_path.replace('.txt', '_price_audit.json')
    auditor.save_report(report, report_path)
    print(f"Full price report saved to: {report_path}")

    if report.over_budget:
        print(
            f"\n⚠  DECK IS OVER BUDGET by ${report.overage:.2f}. "
            f"Review flagged cards and find cheaper printings or substitutes.\n"
        )
        sys.exit(1)


def build_new_deck(
    commander_name: str,
    budget: float,
    output_path: str
) -> None:
    """
    Build mode: generate a new optimized Commander deck from scratch.
    Fetches card pool → scores → assembles within budget → validates → outputs.
    """
    print(f"\n🔨  BUILD MODE")
    print(f"    Commander: {commander_name}")
    print(f"    Budget ceiling: ${budget:.2f}")
    print(f"    Output: {output_path}\n")

    # Step 1: Fetch commander profile and color identity
    print("Step 1/4: Resolving commander color identity...")
    fetcher = CommanderCardFetcher()
    identity = fetcher.resolve_commander_identity(commander_name)
    print(f"  Color identity: {identity or ['Colorless']}\n")

    # Step 2: Fetch entire legal card pool
    print("Step 2/4: Fetching Commander-legal card pool from Scryfall...")
    print("  (This fetches all legal cards — may take 1–2 minutes)\n")
    raw_cards = fetcher.fetch_legal_cards(identity)
    card_pool = fetcher.process_cards(raw_cards)
    print(f"  Fetched {len(card_pool)} cards in color identity.\n")

    # Step 3: Optimize for budget
    print(f"Step 3/4: Assembling deck within ${budget:.2f} budget...")
    optimizer = BudgetOptimizer(budget_ceiling=budget)
    deck = optimizer.optimize(card_pool, commander_name)
    optimizer.print_deck(deck)

    # Step 4: Validate the assembled deck
    print("Step 4/4: Validating assembled deck for format legality...")
    assembled_cards = [
        (card['quantity'], card['card_name'])
        for card in deck.cards
    ]

    engine = CommanderConstraintEngine()
    validation = engine.validate_deck(commander_name, assembled_cards)

    if validation.is_valid:
        print("  ✓ Assembled deck passes all format legality checks\n")
    else:
        print(f"  ✗ {len(validation.errors)} legality issue(s) found — manual review needed:")
        for err in validation.errors:
            print(f"    • {err}")
        print()

    # Output the decklist
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"// Commander: {commander_name}\n")
        f.write(f"// Budget: ${deck.total_cost:.2f} / ${budget:.2f}\n")
        f.write(f"// Generated by MTG AI Deck Builder\n\n")

        # Group by role
        from collections import defaultdict
        by_role = defaultdict(list)
        for card in deck.cards:
            by_role[card['role']].append(card)

        for role, cards in sorted(by_role.items()):
            f.write(f"// {role.upper()}\n")
            for card in sorted(cards, key=lambda c: c['card_name']):
                f.write(f"{card['quantity']} {card['card_name']}\n")
            f.write("\n")

    # Also save JSON with full card data
    json_path = output_path.replace('.txt', '_build_data.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'commander': commander_name,
            'budget_ceiling': budget,
            'total_cost': deck.total_cost,
            'card_count': deck.card_count,
            'within_budget': deck.is_within_budget,
            'warnings': deck.warnings,
            'cards': deck.cards
        }, f, indent=2)

    print(f"Decklist saved to: {output_path}")
    print(f"Build data saved to: {json_path}")

    if deck.warnings:
        print(f"\n⚠  {len(deck.warnings)} warning(s) — review before finalizing:")
        for w in deck.warnings:
            print(f"   • {w}")


def parse_args():
    parser = argparse.ArgumentParser(
        description='MTG AI Commander Deck Builder — build or audit Commander decks with live pricing.'
    )
    parser.add_argument(
        '--commander', '-c',
        type=str,
        required=True,
        help='Exact commander card name (e.g. "Madame Null, Power Broker")'
    )
    parser.add_argument(
        '--budget', '-b',
        type=float,
        default=100.0,
        help='Budget ceiling in USD, excluding basic lands (default: 100.0)'
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        '--audit', '-a',
        type=str,
        metavar='DECKLIST_PATH',
        help='Audit mode: validate and price-check an existing decklist'
    )
    mode_group.add_argument(
        '--output', '-o',
        type=str,
        default='commander_decks/output_deck.txt',
        help='Build mode: path for the generated decklist (default: commander_decks/output_deck.txt)'
    )

    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()

    if args.audit:
        audit_existing_deck(args.audit, args.commander, args.budget)
    else:
        build_new_deck(args.commander, args.budget, args.output)

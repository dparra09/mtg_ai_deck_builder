"""
commander/fetch_commander_cards.py

Fetches all Commander-legal cards from Scryfall filtered by a commander's
color identity. Extends the existing fetch_standard_legal_cards.py pattern
to support the Commander format.

Usage:
    python commander/fetch_commander_cards.py --color-identity B
    python commander/fetch_commander_cards.py --color-identity UB --output data/ub_cards.csv
    python commander/fetch_commander_cards.py --commander "Madame Null, Power Broker"
"""

import argparse
import logging
import os
import time
from typing import Any, Optional
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Color abbreviation map for CLI convenience
COLOR_MAP = {
    'W': 'W', 'U': 'U', 'B': 'B', 'R': 'R', 'G': 'G', 'C': 'C',
    'white': 'W', 'blue': 'U', 'black': 'B', 'red': 'R', 'green': 'G',
    'colorless': 'C'
}


class CommanderCardFetcher:
    """
    Fetches Commander-legal cards from Scryfall filtered by color identity.
    Produces a DataFrame compatible with the existing deck analysis pipeline.
    """

    BASE_URL = "https://api.scryfall.com"
    REQUEST_DELAY = 0.1  # 100ms per Scryfall guidelines

    def __init__(self, app_name: str = "MTGAIDeckBuilder/2.0"):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': app_name,
            'Accept': 'application/json'
        })

    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        time.sleep(self.REQUEST_DELAY)
        try:
            response = self.session.get(
                f"{self.BASE_URL}/{endpoint}",
                params=params,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.warning("Rate limited — waiting 2s before retry")
                time.sleep(2)
                return self._make_request(endpoint, params)
            logger.error(f"HTTP {e.response.status_code}: {e}")
            return None
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None

    def resolve_commander_identity(self, commander_name: str) -> list[str]:
        """
        Look up a commander by name and return its color identity.
        Useful when you'd rather pass the commander name than type out colors.
        """
        logger.info(f"Resolving color identity for: {commander_name}")
        data = self._make_request('cards/named', {'exact': commander_name})
        if not data:
            raise ValueError(f"Commander not found: {commander_name}")
        identity = data.get('color_identity', [])
        logger.info(f"Color identity: {identity or ['Colorless']}")
        return identity

    def build_scryfall_query(self, color_identity: list[str]) -> str:
        """
        Build a Scryfall query string for Commander-legal cards
        matching the given color identity.

        Scryfall's 'id<=' operator matches cards whose color identity
        is a subset of the specified identity — exactly what Commander needs.
        """
        if not color_identity:
            # Colorless commander — only colorless cards are legal
            query = 'format:commander legal:commander id:c'
        else:
            # id<= means "color identity is within" this identity
            identity_str = ''.join(sorted(color_identity))
            query = f'format:commander legal:commander id<={identity_str}'

        logger.info(f"Scryfall query: {query}")
        return query

    def fetch_legal_cards(self, color_identity: list[str]) -> list[dict[str, Any]]:
        """
        Fetch all Commander-legal cards matching the color identity.
        Handles pagination automatically.
        """
        query = self.build_scryfall_query(color_identity)
        cards = []

        params = {
            'q': query,
            'unique': 'cards',
            'order': 'cmc',
        }

        logger.info("Fetching Commander-legal cards from Scryfall...")
        data = self._make_request('cards/search', params)
        if not data:
            raise RuntimeError("Failed to fetch cards from Scryfall")

        cards.extend(data.get('data', []))
        total = data.get('total_cards', 0)
        logger.info(f"Total cards in color identity: {total}")

        while data.get('has_more') and data.get('next_page'):
            logger.info(f"  Fetched {len(cards)}/{total}...")
            time.sleep(self.REQUEST_DELAY)
            try:
                response = self.session.get(data['next_page'], timeout=10)
                response.raise_for_status()
                data = response.json()
                cards.extend(data.get('data', []))
            except Exception as e:
                logger.error(f"Pagination error: {e}")
                break

        logger.info(f"Fetched {len(cards)} total cards")
        return cards

    def process_cards(self, raw_cards: list[dict[str, Any]]) -> pd.DataFrame:
        """
        Process raw Scryfall card data into a structured DataFrame.
        Mirrors the schema from fetch_standard_legal_cards.py for
        compatibility with existing analysis pipeline.
        Adds Commander-specific fields: prices, color_identity_str.
        """
        processed = []

        for card in raw_cards:
            name = card.get('name', '')
            layout = card.get('layout', '')
            type_line = card.get('type_line', '')

            # Handle dual-faced cards
            if 'card_faces' in card and card['card_faces']:
                front = card['card_faces'][0]
                mana_cost = front.get('mana_cost', card.get('mana_cost', ''))
                colors = front.get('colors', card.get('colors', []))
                oracle_text = front.get('oracle_text', '')
                power = front.get('power', card.get('power', ''))
                toughness = front.get('toughness', card.get('toughness', ''))

                if len(card['card_faces']) > 1:
                    back = card['card_faces'][1]
                    back_oracle = back.get('oracle_text', '')
                    if '//' in name:
                        oracle_text = f"{oracle_text}\n\n{back_oracle}"
            else:
                mana_cost = card.get('mana_cost', '')
                colors = card.get('colors', [])
                oracle_text = card.get('oracle_text', '')
                power = card.get('power', '')
                toughness = card.get('toughness', '')

            color_identity = card.get('color_identity', [])
            prices = card.get('prices', {})

            row = {
                # Core identity fields (compatible with existing pipeline)
                'name': name.split('//')[0].strip() if '//' in name else name,
                'full_name': name,
                'layout': layout,
                'mana_cost': mana_cost,
                'cmc': card.get('cmc'),
                'type_line': type_line,
                'oracle_text': oracle_text,
                'colors': colors,
                'color_identity': color_identity,
                'color_identity_str': ''.join(sorted(color_identity)) or 'C',
                'power': power,
                'toughness': toughness,
                'rarity': card.get('rarity'),
                'set': card.get('set'),
                'collector_number': card.get('collector_number'),
                'keywords': card.get('keywords', []),
                'produced_mana': card.get('produced_mana', []),
                'legalities': card.get('legalities', {}),
                # Commander-specific fields
                'usd_price': float(prices['usd']) if prices.get('usd') else None,
                'usd_foil_price': float(prices['usd_foil']) if prices.get('usd_foil') else None,
                'scryfall_id': card.get('id', ''),
                'edhrec_rank': card.get('edhrec_rank'),  # Proxy for Commander popularity
                # Derived fields
                'is_creature': 'Creature' in type_line,
                'is_land': 'Land' in type_line,
                'is_instant_sorcery': any(t in type_line for t in ['Instant', 'Sorcery']),
                'is_artifact': 'Artifact' in type_line,
                'is_enchantment': 'Enchantment' in type_line,
                'is_multicolored': len(colors) > 1,
                'is_legendary': 'Legendary' in type_line,
                'has_etb_effect': 'enters' in (oracle_text or '').lower(),
                'is_ramp': any(kw in (oracle_text or '').lower() for kw in [
                    'add {', 'search your library for a', 'basic land'
                ]),
                'is_removal': any(kw in (oracle_text or '').lower() for kw in [
                    'destroy target', 'exile target', 'deals damage to target'
                ]),
                'is_draw': any(kw in (oracle_text or '').lower() for kw in [
                    'draw a card', 'draw two', 'draw cards'
                ]),
            }
            processed.append(row)

        return pd.DataFrame(processed)

    def save_to_csv(self, df: pd.DataFrame, output_path: str) -> str:
        """Save card data to CSV, creating output directory if needed."""
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
        df.to_csv(output_path, index=False)
        logger.info(f"Saved {len(df)} cards to: {output_path}")
        return output_path


def parse_args():
    parser = argparse.ArgumentParser(
        description='Fetch Commander-legal cards from Scryfall filtered by color identity.'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--color-identity',
        type=str,
        help='Color identity string, e.g. "B" (mono-black), "UB" (blue-black), "WUBRG" (5-color)'
    )
    group.add_argument(
        '--commander',
        type=str,
        help='Commander name — color identity will be resolved automatically'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output CSV path (default: data/commander_{identity}_cards.csv)'
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    fetcher = CommanderCardFetcher()

    if args.commander:
        identity = fetcher.resolve_commander_identity(args.commander)
    else:
        identity = [COLOR_MAP.get(c.upper(), c.upper()) for c in args.color_identity]

    identity_str = ''.join(sorted(identity)) or 'C'
    output_path = args.output or f"data/commander_{identity_str.lower()}_cards.csv"

    raw_cards = fetcher.fetch_legal_cards(identity)
    df = fetcher.process_cards(raw_cards)
    fetcher.save_to_csv(df, output_path)

    print(f"\nDataset Overview — Color Identity: {identity or ['Colorless']}")
    print(f"Total cards: {len(df)}")
    print(f"Creatures:    {df['is_creature'].sum()}")
    print(f"Lands:        {df['is_land'].sum()}")
    print(f"Artifacts:    {df['is_artifact'].sum()}")
    print(f"Enchantments: {df['is_enchantment'].sum()}")
    print(f"Instants/Sorceries: {df['is_instant_sorcery'].sum()}")
    print(f"With ETB effects: {df['has_etb_effect'].sum()}")
    if 'usd_price' in df.columns:
        priced = df[df['usd_price'].notna()]
        print(f"\nPriced cards: {len(priced)}")
        print(f"Median price: ${priced['usd_price'].median():.2f}")
        print(f"Cards under $1: {(priced['usd_price'] < 1.0).sum()}")
        print(f"Cards under $5: {(priced['usd_price'] < 5.0).sum()}")
        print(f"Cards over $15: {(priced['usd_price'] > 15.0).sum()}")
    print(f"\nSaved to: {output_path}")

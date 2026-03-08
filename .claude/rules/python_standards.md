# Python Standards
# Applies to: all .py files in this project

## Style
- Python 3.10+ features are allowed (match/case, union types with |)
- Type hints required on all public functions and class methods
- PEP 8 compliance, 100-character line limit
- Docstrings on all classes and public methods (Google style)

## Structure Patterns
- Use classes for stateful components (scrapers, analyzers, fetchers)
- Use standalone functions for pure logic (scoring, filtering, validation)
- Separate I/O from logic — functions that fetch data should not also
  write files; keep those responsibilities in distinct methods

## Logging
```python
import logging
logger = logging.getLogger(__name__)
# Use logger.info(), logger.warning(), logger.error() — never print() in modules
# print() is acceptable only in __main__ blocks for user-facing CLI output
```

## HTTP Requests
```python
# Always use Session with browser-like headers
session = requests.Session()
session.headers.update({
    'User-Agent': 'MTGAIDeckBuilder/2.0 (contact: your@email.com)',
    'Accept': 'application/json'
})

# Rate limiting — respect API guidelines
time.sleep(0.1)   # Scryfall: 100ms between requests
time.sleep(2.0)   # MTGGoldfish: 2s between requests (scraping)
```

## Error Handling
```python
# Always catch specific exceptions, not bare except
try:
    response = session.get(url, timeout=10)
    response.raise_for_status()
except requests.exceptions.Timeout:
    logger.error(f"Timeout fetching {url}")
    return None
except requests.exceptions.HTTPError as e:
    logger.error(f"HTTP {e.response.status_code} for {url}")
    return None
```

## File I/O
- All CSV outputs → `data/` directory
- All JSON outputs → `json_outputs/` directory
- All deck text files → `current_standard_decks/` or `commander_decks/`
- Create output directories with `os.makedirs(dir, exist_ok=True)`

## CLI Interfaces
```python
# Use argparse for all scripts intended to be run directly
import argparse

def parse_args():
    parser = argparse.ArgumentParser(description='...')
    parser.add_argument('--commander', type=str, required=True)
    parser.add_argument('--budget', type=float, default=100.0)
    return parser.parse_args()
```

## Testing Conventions
- Test files in `tests/` directory mirroring the source structure
- Use pytest
- Test pure logic functions aggressively; mock all HTTP calls

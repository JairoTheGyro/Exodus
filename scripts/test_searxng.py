#!/usr/bin/env python3
"""Verify the same bounded JSON search used by the Exodus agent; no LLM needed."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('--categories', default=None)
    parser.add_argument('--count', type=int, choices=(3, 4, 5), default=5)
    args = parser.parse_args()
    from services.search.providers import compact_searxng_search, SearXNGUnavailable
    try:
        results = compact_searxng_search(args.query, args.count, args.categories)
        print(json.dumps({'results': results, 'count': len(results)}, indent=2, ensure_ascii=False))
        return 0
    except (SearXNGUnavailable, ValueError) as exc:
        print(json.dumps({'results': [], 'error': str(exc)}, ensure_ascii=False))
        return 1

if __name__ == '__main__': sys.exit(main())

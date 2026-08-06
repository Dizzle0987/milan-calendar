#!/usr/bin/env python3
from __future__ import annotations

import logging
import sys
from pathlib import Path

from milan_calendar import UpdateError, update_calendar


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        events = update_calendar(Path(__file__).parent)
    except (UpdateError, ValueError) as exc:
        logging.error("%s", exc)
        return 1
    logging.info("Calendario aggiornato: %d partite", len(events))
    return 0


if __name__ == "__main__":
    sys.exit(main())

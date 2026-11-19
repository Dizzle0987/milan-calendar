"""Notify about technical discovery failures, never about missing free coverage."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess

TITLE = "⚠️ Milan Calendar: problemi nelle guide TV internazionali"


def evaluate(payload: dict, registry: dict, now: datetime) -> list[str]:
    monitored = [s["broadcaster"] for s in registry.get("sources", []) if s.get("health_monitor")]
    relevant = []
    for event in payload.get("events", []):
        if not event.get("broadcast_show_possible"):
            continue
        try:
            start = datetime.fromisoformat(str(event["start"]).replace("Z", "+00:00"))
            if start.tzinfo is None:
                continue
        except (KeyError, ValueError):
            continue
        if now <= start <= now + timedelta(days=7):
            relevant.append(event)
    if not relevant:
        return []
    return sorted({str(error) for error in payload.get("source_errors", [])
                   if any(str(error).startswith("Broadcast " + name + " (")
                          or str(error).startswith("Broadcast " + name + ":") for name in monitored)})


def notify(problems: list[str], repo: str, run_url: str) -> None:
    def gh(*args: str) -> str:
        return subprocess.check_output(["gh", *args, "--repo", repo], text=True)
    issues = json.loads(gh("issue", "list", "--state", "open", "--limit", "100", "--json", "number,title,body"))
    existing = next((issue for issue in issues if issue["title"] == TITLE), None)
    if problems:
        body = ("@Dizzle0987 alcune guide internazionali hanno errori tecnici mentre si avvicina una partita.\n\n"
                + "\n".join("- " + item for item in problems)
                + "\n\nNon significa che la partita non sia trasmessa: la ricerca è incompleta. "
                "Il calendario valido resta disponibile e le fonti verranno riprovate automaticamente.\n\n"
                + "Esecuzione: " + run_url)
        if not existing:
            gh("issue", "create", "--title", TITLE, "--body", body)
        elif existing.get("body", "").split("\n\nEsecuzione:")[0] != body.split("\n\nEsecuzione:")[0]:
            gh("issue", "edit", str(existing["number"]), "--body", body)
    elif existing:
        gh("issue", "close", str(existing["number"]), "--reason", "completed",
           "--comment", "Controllo rientrato: nessun errore tecnico monitorato nelle partite entro 7 giorni. " + run_url)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "data/events.json").read_text())
    registry = json.loads((root / "data/broadcast_sources.json").read_text())
    problems = evaluate(payload, registry, datetime.now(timezone.utc))
    print(json.dumps({"problems": problems}, ensure_ascii=False))
    if args.notify:
        notify(problems, os.environ["GITHUB_REPOSITORY"], os.environ.get("SOURCE_RUN_URL", ""))


if __name__ == "__main__":
    main()

"""
Caliceo Lieusaint - Collecteur d'affluence
==========================================

Ce script récupère l'affluence en direct du spa Caliceo Lieusaint
(https://lieusaint.caliceo.com/) et la stocke dans une base SQLite.

Il est conçu pour être exécuté toutes les heures via une tâche planifiée
(cron sous Linux/macOS, Task Scheduler sous Windows).

Stratégie :
- Le site rend l'affluence côté client (JavaScript), on utilise donc
  Playwright (navigateur headless Chromium) pour exécuter le JS.
- On attend que la valeur "Affluence en direct : X%" soit rendue,
  puis on extrait le pourcentage.
- On stocke chaque mesure dans data.sqlite avec horodatage local.

Usage :
    python collect.py
"""

from __future__ import annotations

import logging
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Fuseau horaire de référence (Caliceo Lieusaint est en France).
# Forcer ce fuseau garantit que les données sont cohérentes même quand
# le script tourne sur un serveur en UTC (ex. GitHub Actions).
TZ_PARIS = ZoneInfo("Europe/Paris")

# Playwright est importé à l'intérieur de main() pour donner un message
# d'erreur clair si le package n'est pas installé.

# --- Configuration ---------------------------------------------------------

URL = "https://lieusaint.caliceo.com/"
DB_PATH = Path(__file__).parent / "data.sqlite"
LOG_PATH = Path(__file__).parent / "collect.log"
TIMEOUT_MS = 30_000  # 30 secondes max pour charger la page
MAX_RETRIES = 3
RETRY_DELAY_SEC = 10

# --- Logging ---------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("caliceo")


# --- Base de données -------------------------------------------------------


def init_db() -> sqlite3.Connection:
    """Crée la table si elle n'existe pas et retourne la connexion."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,   -- ISO 8601, heure locale
            iso_week    INTEGER NOT NULL,
            weekday     INTEGER NOT NULL,   -- 0 = lundi, 6 = dimanche
            hour        INTEGER NOT NULL,
            minute      INTEGER NOT NULL,
            attendance  INTEGER NOT NULL,   -- pourcentage 0-100
            raw_text    TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_timestamp ON attendance(timestamp)"
    )
    conn.commit()
    return conn


def store(conn: sqlite3.Connection, value: int, raw: str) -> None:
    now = datetime.now(TZ_PARIS)
    conn.execute(
        """
        INSERT INTO attendance
            (timestamp, iso_week, weekday, hour, minute, attendance, raw_text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now.isoformat(timespec="seconds"),
            now.isocalendar().week,
            now.weekday(),
            now.hour,
            now.minute,
            value,
            raw,
        ),
    )
    conn.commit()


# --- Scraping --------------------------------------------------------------


def fetch_attendance() -> tuple[int, str]:
    """
    Ouvre la page Caliceo dans Chromium (headless), attend que l'affluence
    soit rendue, et retourne (pourcentage, texte brut).

    Lève RuntimeError si l'extraction échoue après MAX_RETRIES tentatives.
    """
    from playwright.sync_api import sync_playwright

    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        log.info("Tentative %d/%d ...", attempt, MAX_RETRIES)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                    locale="fr-FR",
                )
                page = context.new_page()
                page.goto(URL, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

                # Le texte "Affluence en direct : X%" est rendu après le JS.
                # On attend qu'il apparaisse dans le DOM.
                page.wait_for_function(
                    """() => {
                        const txt = document.body.innerText;
                        return /Affluence\\s+en\\s+direct\\s*:\\s*\\d+\\s*%/i.test(txt);
                    }""",
                    timeout=TIMEOUT_MS,
                )

                body_text = page.evaluate("() => document.body.innerText")
                browser.close()

            # Extraction du pourcentage
            match = re.search(
                r"Affluence\s+en\s+direct\s*:\s*(\d+)\s*%",
                body_text,
                flags=re.IGNORECASE,
            )
            if not match:
                raise RuntimeError(
                    "Motif 'Affluence en direct : X%' introuvable dans le DOM"
                )

            pct = int(match.group(1))
            raw = match.group(0)
            log.info("Affluence détectée : %d%% (texte brut : %r)", pct, raw)
            return pct, raw

        except Exception as exc:  # noqa: BLE001
            last_error = exc
            log.warning("Échec tentative %d : %s", attempt, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SEC)

    raise RuntimeError(
        f"Impossible de récupérer l'affluence après {MAX_RETRIES} tentatives : {last_error}"
    )


# --- Main ------------------------------------------------------------------


def main() -> int:
    log.info("=== Démarrage de la collecte ===")

    try:
        import playwright  # noqa: F401
    except ImportError:
        log.error(
            "Playwright n'est pas installé. Exécutez :\n"
            "    pip install playwright\n"
            "    playwright install chromium"
        )
        return 2

    try:
        pct, raw = fetch_attendance()
    except Exception as exc:  # noqa: BLE001
        log.error("Échec de la collecte : %s", exc)
        return 1

    conn = init_db()
    try:
        store(conn, pct, raw)
        count = conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
        log.info("Mesure enregistrée. Total en base : %d lignes.", count)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())

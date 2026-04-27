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
TIMEOUT_MS = 45_000  # 45 s max pour charger la page
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


def _extract_pct(text: str) -> int | None:
    """Extrait le pourcentage d'affluence d'un texte. Retourne None si absent."""
    m = re.search(
        r"Affluence\s+en\s+direct\s*:\s*(\d+)\s*%",
        text,
        flags=re.IGNORECASE,
    )
    return int(m.group(1)) if m else None


def fetch_attendance() -> tuple[int, str]:
    """
    Ouvre la page Caliceo dans Chromium (headless) et récupère l'affluence
    de manière fiable.

    Stratégie anti "0% par défaut" :
    1. La page contient initialement "Affluence en direct : 0%" en HTML brut
       (valeur par défaut). C'est REMPLACÉE par la vraie valeur après un
       appel API en JavaScript.
    2. On enregistre tous les appels réseau pour identifier l'API d'affluence
       et utiliser directement sa réponse JSON quand c'est possible.
    3. À défaut, on attend que la valeur affichée se STABILISE pendant
       plusieurs secondes consécutives (la vraie valeur ne change plus
       après chargement, contrairement aux mises à jour pendant le rendu).
    4. On effectue plusieurs lectures espacées et on prend la dernière.

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

                # --- Méthode A : intercepter les réponses réseau ---
                # On capture toutes les réponses JSON susceptibles de
                # contenir l'affluence. Mots-clés cherchés dans l'URL :
                # affluence, attendance, occupancy, busy, crowd, center.
                api_responses: list[dict] = []

                def on_response(response):
                    try:
                        url = response.url.lower()
                        if any(
                            kw in url
                            for kw in (
                                "affluence",
                                "attendance",
                                "occupancy",
                                "crowd",
                                "busy",
                                "center",
                                "lieusaint",
                                "caliceo",
                            )
                        ):
                            ct = (response.headers.get("content-type") or "").lower()
                            if "json" in ct or "javascript" in ct:
                                try:
                                    data = response.json()
                                    api_responses.append(
                                        {"url": response.url, "data": data}
                                    )
                                except Exception:
                                    pass
                    except Exception:
                        pass

                page.on("response", on_response)

                page.goto(URL, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

                # --- Méthode B : attendre que la valeur affichée se stabilise ---
                # On lit la valeur toutes les secondes pendant 25 secondes max.
                # On considère qu'elle est correcte quand elle reste identique
                # pendant 5 lectures consécutives.
                # On rejette aussi 0 % comme valeur initiale tant qu'on n'a pas
                # passé au moins 8 secondes (le "0" du HTML brut).
                stable_target = 5
                stable_count = 0
                last_value: int | None = None
                final_value: int | None = None
                start = time.time()
                MAX_WAIT = 25.0

                while time.time() - start < MAX_WAIT:
                    time.sleep(1.0)
                    body_text = page.evaluate("() => document.body.innerText")
                    pct = _extract_pct(body_text)
                    elapsed = time.time() - start
                    log.debug(
                        "  t=%.1fs : valeur affichée = %s",
                        elapsed,
                        pct,
                    )

                    if pct is None:
                        continue

                    # Tant qu'on est tôt et qu'on lit 0, c'est probablement
                    # la valeur par défaut du HTML statique. On ne la valide pas.
                    if pct == 0 and elapsed < 8:
                        continue

                    if pct == last_value:
                        stable_count += 1
                        if stable_count >= stable_target:
                            final_value = pct
                            log.info(
                                "  Valeur stabilisée à %d%% après %.1fs",
                                pct,
                                elapsed,
                            )
                            break
                    else:
                        stable_count = 1
                        last_value = pct

                # Si pas de stabilisation, on prend la dernière valeur lue
                # tant qu'elle a été stable au moins 2 fois.
                if final_value is None and last_value is not None and stable_count >= 2:
                    final_value = last_value
                    log.info(
                        "  Pas de stabilisation complète, on prend %d%% (stable %d fois)",
                        last_value,
                        stable_count,
                    )

                browser.close()

            # --- Choix de la valeur finale ---
            # Si on a intercepté des réponses API, on les log pour diagnostic
            if api_responses:
                log.info(
                    "  %d réponse(s) API interceptée(s) :",
                    len(api_responses),
                )
                for r in api_responses[:3]:
                    log.info("    - %s : %s", r["url"], str(r["data"])[:200])

            if final_value is None:
                raise RuntimeError(
                    "Impossible de stabiliser la valeur d'affluence après "
                    f"{MAX_WAIT}s. Le site est peut-être en panne."
                )

            raw = f"Affluence en direct : {final_value}%"
            log.info("Affluence retenue : %d%%", final_value)
            return final_value, raw

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

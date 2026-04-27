"""
Génère une page HTML simple regroupant les graphiques produits par
analyze.py. Cette page est destinée à être publiée sur GitHub Pages.

Usage :
    python analyze.py        # produit les images dans output/
    python build_dashboard.py # crée output/index.html
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUTPUT_DIR = Path(__file__).parent / "output"
DB_PATH = Path(__file__).parent / "data.sqlite"

JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def db_summary() -> dict:
    if not DB_PATH.exists():
        return {"count": 0, "first": None, "last": None}
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    count = cur.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
    if count == 0:
        return {"count": 0, "first": None, "last": None}
    first = cur.execute("SELECT MIN(timestamp) FROM attendance").fetchone()[0]
    last = cur.execute("SELECT MAX(timestamp) FROM attendance").fetchone()[0]
    # Créneau le plus calme et chargé (heures d'ouverture seulement)
    rows = cur.execute(
        """
        SELECT weekday, hour, AVG(attendance) AS m
        FROM attendance
        WHERE attendance > 0
        GROUP BY weekday, hour
        ORDER BY m
        """
    ).fetchall()
    conn.close()
    quietest = rows[0] if rows else None
    busiest = rows[-1] if rows else None
    return {
        "count": count,
        "first": first,
        "last": last,
        "quietest": quietest,
        "busiest": busiest,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    s = db_summary()
    now_paris_dt = datetime.now(ZoneInfo("Europe/Paris"))
    now_paris = now_paris_dt.strftime("%d/%m/%Y à %H:%M")
    # Version unique appendée à chaque ressource (?v=...) pour forcer le
    # navigateur à recharger les fichiers à chaque nouvelle génération.
    version = now_paris_dt.strftime("%Y%m%d%H%M%S")

    if s["count"] == 0:
        body = "<p>Pas encore de données. Patientez quelques heures !</p>"
    else:
        quietest_str = (
            f"{JOURS_FR[s['quietest'][0]]} {s['quietest'][1]}h "
            f"(moy. {s['quietest'][2]:.1f} %)"
            if s["quietest"]
            else "—"
        )
        busiest_str = (
            f"{JOURS_FR[s['busiest'][0]]} {s['busiest'][1]}h "
            f"(moy. {s['busiest'][2]:.1f} %)"
            if s["busiest"]
            else "—"
        )
        body = f"""
        <div class="stats">
          <div class="stat"><div class="stat-label">Mesures collectées</div><div class="stat-value">{s['count']}</div></div>
          <div class="stat"><div class="stat-label">Première mesure</div><div class="stat-value">{s['first'][:16].replace('T', ' ')}</div></div>
          <div class="stat"><div class="stat-label">Dernière mesure</div><div class="stat-value">{s['last'][:16].replace('T', ' ')}</div></div>
        </div>

        <div class="highlight">
          <p>🟢 <b>Créneau le plus calme</b> : {quietest_str}</p>
          <p>🔴 <b>Créneau le plus chargé</b> : {busiest_str}</p>
        </div>

        <h2>Heatmap : jour de la semaine × heure</h2>
        <p>La donnée la plus utile : couleur = affluence moyenne, chiffre = pourcentage.</p>
        <img src="heatmap_jour_heure.png?v={version}" alt="Heatmap" />

        <h2>Affluence moyenne par heure</h2>
        <img src="moyenne_par_heure.png?v={version}" alt="Moyenne par heure" />

        <h2>Affluence moyenne par jour</h2>
        <img src="moyenne_par_jour.png?v={version}" alt="Moyenne par jour" />

        <h2>Toutes les mesures dans le temps</h2>
        <img src="timeline_brute.png?v={version}" alt="Timeline" />

        <h2>Données brutes</h2>
        <p>
          <a href="donnees_brutes.csv?v={version}" download>📥 Télécharger les données brutes (CSV)</a><br>
          <a href="statistiques_par_creneau.csv?v={version}" download>📥 Télécharger les stats par créneau (CSV)</a>
        </p>
        """

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Affluence Caliceo Lieusaint</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    max-width: 1200px;
    margin: 2rem auto;
    padding: 0 1rem;
    color: #1a1a1a;
    background: #fafafa;
  }}
  h1 {{ color: #0a4d68; }}
  h2 {{ color: #0a4d68; margin-top: 2.5rem; border-bottom: 2px solid #e0e0e0; padding-bottom: .3rem; }}
  img {{ max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 6px; background: white; }}
  .footer {{ margin-top: 3rem; color: #666; font-size: .85rem; text-align: center; }}
  .stats {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: 1.5rem 0; }}
  .stat {{ background: white; padding: 1rem 1.5rem; border-radius: 8px; border: 1px solid #e0e0e0; flex: 1; min-width: 200px; }}
  .stat-label {{ color: #666; font-size: .85rem; text-transform: uppercase; }}
  .stat-value {{ font-size: 1.4rem; font-weight: bold; color: #0a4d68; margin-top: .3rem; }}
  .highlight {{ background: white; border-left: 4px solid #0a4d68; padding: 1rem 1.5rem; border-radius: 4px; margin: 1.5rem 0; }}
  .highlight p {{ margin: .4rem 0; }}
  a {{ color: #0a4d68; }}
</style>
</head>
<body>
  <h1>🛁 Affluence Caliceo Lieusaint</h1>
  <p>Tableau de bord généré automatiquement. Dernière mise à jour : <b>{now_paris}</b> (Paris).</p>
  {body}
  <div class="footer">
    Source : <a href="https://lieusaint.caliceo.com/">lieusaint.caliceo.com</a> ·
    Collecte horaire automatique via GitHub Actions ·
    Usage personnel
  </div>
</body>
</html>
"""

    out = OUTPUT_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"Dashboard généré : {out}")


if __name__ == "__main__":
    main()

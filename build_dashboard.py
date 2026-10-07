"""
Génère une page HTML simple regroupant les graphiques produits par
analyze.py. Cette page est destinée à être publiée sur GitHub Pages.

Usage :
    python analyze.py        # produit les images dans output/
    python build_dashboard.py # crée output/index.html
"""

from __future__ import annotations

import json
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


def fmt(v, suffixe: str = " %", signe: bool = False) -> str:
    if v is None:
        return "—"
    return (f"{v:+.1f}" if signe else f"{v:.1f}") + suffixe


def couleur(v) -> str:
    """Même code couleur que la heatmap : confortable < 35 % ≤ moyen < 55 % ≤ chargé."""
    if v is None:
        return ""
    if v >= 55:
        return "lvl-high"
    if v >= 35:
        return "lvl-mid"
    return "lvl-low"


def forecast_sections(version: str) -> str:
    """Sections prévision + tableaux mensuel/saisonnier (produits par forecast.py)."""
    path = OUTPUT_DIR / "forecast_summary.json"
    if not path.exists():
        return ""
    f = json.loads(path.read_text(encoding="utf-8"))
    bt = f.get("backtest") or {}

    # --- Prévision ---
    lignes_jours = ""
    for j in f["jours"]:
        notes = []
        if j["ferie"]:
            notes.append(f"★ {j['ferie']}")
        if j["vacances"]:
            notes.append(f"Vacances ({j['vacances']})")
        if j["calendrier_inconnu"]:
            notes.append("calendrier scolaire non renseigné")
        lignes_jours += f"""
          <tr>
            <td><b>{j['jour']}</b>{'<br><small>' + ' · '.join(notes) + '</small>' if notes else ''}</td>
            <td class="{couleur(j['moyenne'])}">{j['moyenne']} %</td>
            <td>{j['creneau_calme']} <small>({j['creneau_calme_val']} %)</small></td>
            <td class="{couleur(j['pic_val'])}">{j['pic']} <small>({j['pic_val']} %, jusqu'à {j['pic_haut']} %)</small></td>
          </tr>"""

    if bt:
        demi_vie = (f"{bt['demi_vie_semaines']} semaines" if bt["demi_vie_semaines"]
                    else "aucune (toutes les semaines comptent autant)")
        mae = bt["mae"]
        fiabilite = f"""
        <div class="highlight">
          <p><b>Fiabilité mesurée</b> (prévisions refaites sur les {bt['n_semaines']} dernières semaines, sans voir leurs données) :</p>
          <table class="data compact">
            <tr><th>Méthode</th><th>Erreur moyenne</th></tr>
            <tr><td><b>Ce modèle</b></td><td><b>{fmt(mae['modele'], ' pts')}</b></td></tr>
            <tr><td>Moyenne historique du créneau</td><td>{fmt(mae['moyenne_creneau'], ' pts')}</td></tr>
            <tr><td>Même créneau la semaine précédente</td><td>{fmt(mae['semaine_precedente'], ' pts')}</td></tr>
          </table>
          <p><small>Comparaison sur {bt['n_creneaux_comparaison']} créneaux où les 3 méthodes sont calculables.
          Erreur moyenne du modèle sur les {bt['n_creneaux']} créneaux testés : {fmt(bt['mae_tous_creneaux'], ' pts')}.
          Intervalle à 80 % : de {fmt(bt['intervalle'][0], ' pts', True)} à {fmt(bt['intervalle'][1], ' pts', True)} autour de la prévision ;
          il a contenu la vraie valeur dans {bt['couverture']} % des cas.
          Biais moyen : {fmt(bt['biais'], ' pts', True)} (négatif = le modèle a surestimé).</small></p>
        </div>"""
    else:
        demi_vie = "—"
        fiabilite = "<p><i>Historique encore trop court pour mesurer la fiabilité.</i></p>"

    c = f["coefs"]
    prevision = f"""
        <h2>🔮 Prévision pour les 7 prochains jours</h2>
        <p>Affluence attendue heure par heure. ★ = jour férié ou pont.</p>
        <img src="prevision_semaine.png?v={version}" alt="Prévision 7 jours" />
        <div class="table-wrap">
        <table class="data">
          <tr><th>Jour</th><th>Moyenne prévue</th><th>Créneau le plus calme</th><th>Pic prévu</th></tr>
          {lignes_jours}
        </table>
        </div>
        {fiabilite}
        <details>
          <summary><b>Méthode et hypothèses du modèle</b></summary>
          <p>Régression linéaire sur les {f['n_creneaux']} créneaux horaires mesurés :</p>
          <p class="formula">affluence = moyenne + effet du jour + effet de l'heure + effet jour×heure
            + effet vacances (semaine / week-end) + effet jour férié</p>
          <ul>
            <li>Effets estimés : vacances scolaires en semaine <b>{fmt(c['vacances_semaine'], ' pts', True)}</b>,
                vacances le week-end <b>{fmt(c['vacances_weekend'], ' pts', True)}</b>,
                jour férié/pont <b>{fmt(c['ferie'], ' pts', True)}</b>.</li>
            <li>L'effet jour×heure est « rétréci » vers le profil jour + heure (régression ridge, λ = {bt.get('lambda', '—')}) :
                une case peu mesurée ne s'écarte du profil général que si les données le justifient.</li>
            <li>Pondération des semaines récentes : {demi_vie}. Ce réglage et λ sont choisis automatiquement
                pour minimiser l'erreur sur les semaines passées.</li>
          </ul>
          <p><b>Hypothèses</b></p>
          <ol>
            <li>Le rythme hebdomadaire (jour × heure) est stable dans le temps.</li>
            <li>Vacances et jours fériés décalent l'affluence d'un nombre de points constant, quelle que soit l'heure.
                Toutes les vacances (Toussaint, Noël, été…) ont le même effet.</li>
            <li>La mesure prise dans l'heure (HH:07 à HH:47) représente toute l'heure.</li>
            <li>Un 0 % pendant l'ouverture est une erreur de lecture (sauf à 10h) ; une journée entière à 0 % est une fermeture
                ({', '.join(f['fermetures']) or 'aucune'}) : exclues.</li>
            <li>Horaires : 10h-22h, 10h-23h vendredi et samedi ; fermetures exceptionnelles non connues.</li>
            <li>Météo, événements locaux, promotions : non pris en compte (inclus dans l'incertitude).</li>
            <li>Moins d'un an de données : la saison n'est pas une variable du modèle (pas d'hiver observé).</li>
          </ol>
        </details>
        <p><a href="prevision_semaine.csv?v={version}" download>📥 Télécharger la prévision détaillée (CSV)</a></p>
    """

    # --- Tableau mensuel ---
    lignes_mois = ""
    for m in f["mois"]:
        evo = m["evolution"]
        evo_cls = "" if evo is None else ("up" if evo > 0 else "down" if evo < 0 else "")
        lignes_mois += f"""
          <tr>
            <td><b>{m['mois']}</b>{' <small>(partiel)</small>' if m['partiel'] else ''}</td>
            <td>{m['jours']}</td>
            <td>{m['creneaux']}</td>
            <td>{fmt(m['moyenne_brute'])}</td>
            <td class="{couleur(m['moyenne_ajustee'])}"><b>{fmt(m['moyenne_ajustee'])}</b></td>
            <td class="{evo_cls}">{fmt(evo, ' pts', True)}</td>
            <td>{fmt(m['semaine'])}</td>
            <td>{fmt(m['weekend'])}</td>
            <td>{m['pct_charges']} %</td>
            <td>{m['max']} %</td>
            <td>{m['jour_pointe']} · {m['heure_pointe']}</td>
          </tr>"""
    mois = f"""
        <h2>📅 Affluence par mois</h2>
        <div class="table-wrap">
        <table class="data">
          <tr><th>Mois</th><th>Jours</th><th>Créneaux</th><th>Moyenne brute</th><th>Moyenne ajustée</th>
              <th>Évolution</th><th>Semaine</th><th>Week-end</th><th>Créneaux chargés (≥ 55 %)</th><th>Max</th><th>Pointe</th></tr>
          {lignes_mois}
        </table>
        </div>
        <p><small><b>Moyenne ajustée</b> = moyenne générale ({f['moyenne_globale']} %) + écart moyen du mois par rapport au
        profil habituel de chaque créneau jour×heure. Elle corrige le fait que tous les mois n'ont pas été mesurés aux mêmes
        heures (créneaux manquants, mesures en double) ; c'est elle qu'il faut comparer d'un mois à l'autre.
        « Évolution » = différence de moyenne ajustée avec le mois précédent.</small></p>
    """

    # --- Tableau saisons ---
    lignes_saisons = ""
    for s_ in f["saisons"]:
        if s_["vide"]:
            lignes_saisons += f"""
          <tr><td><b>{s_['groupe']}</b></td><td colspan="8"><i>Pas encore de données</i></td></tr>"""
            continue
        ecart = s_["ecart_global"]
        lignes_saisons += f"""
          <tr{' class="sep"' if s_['groupe'].startswith('Vacances') else ''}>
            <td><b>{s_['groupe']}</b>{' <small>(en cours)</small>' if s_['en_cours'] else ''}<br><small>{s_['debut']} → {s_['fin']}</small></td>
            <td>{s_['jours']}</td>
            <td class="{couleur(s_['moyenne_ajustee'])}"><b>{fmt(s_['moyenne_ajustee'])}</b></td>
            <td class="{'up' if ecart > 0 else 'down' if ecart < 0 else ''}">{fmt(ecart, ' pts', True)}</td>
            <td>{fmt(s_['semaine'])}</td>
            <td>{fmt(s_['weekend'])}</td>
            <td>{s_['pct_charges']} %</td>
            <td>{s_['jour_pointe']} · {s_['heure_pointe']}</td>
          </tr>"""
    saisons = f"""
        <h2>🍂 Tendances par saison</h2>
        <div class="table-wrap">
        <table class="data">
          <tr><th>Période</th><th>Jours</th><th>Moyenne ajustée</th><th>Écart à la moyenne</th>
              <th>Semaine</th><th>Week-end</th><th>Créneaux chargés</th><th>Pointe</th></tr>
          {lignes_saisons}
        </table>
        </div>
        <p><small>Saisons astronomiques (printemps 20/03, été 21/06, automne 22/09, hiver 21/12). Avec moins d'un an
        de données, ces tendances sont descriptives : elles mélangent l'effet de la saison et celui des vacances
        scolaires (comparées dans les deux dernières lignes).</small></p>
        <p>
          <a href="affluence_par_mois.csv?v={version}" download>📥 Tableau mensuel (CSV)</a><br>
          <a href="tendances_saisons.csv?v={version}" download>📥 Tendances par saison (CSV)</a>
        </p>
    """
    return prevision + mois + saisons


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

        {forecast_sections(version)}

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
  .table-wrap {{ overflow-x: auto; margin: 1rem 0; }}
  table.data {{ border-collapse: collapse; width: 100%; background: white; font-size: .92rem; }}
  table.data th, table.data td {{ border: 1px solid #e0e0e0; padding: .45rem .6rem; text-align: left; vertical-align: top; }}
  table.data th {{ background: #f0f4f6; color: #0a4d68; font-weight: 600; }}
  table.data td small {{ color: #666; }}
  table.data.compact {{ width: auto; margin: .5rem 0; }}
  table.data tr.sep td {{ border-top: 2px solid #0a4d68; }}
  .lvl-low {{ background: #e3f4e6; }}
  .lvl-mid {{ background: #fff4d1; }}
  .lvl-high {{ background: #fbe0d6; }}
  .up {{ color: #b03a2e; }}
  .down {{ color: #1a7a3e; }}
  details {{ background: white; border: 1px solid #e0e0e0; border-radius: 6px; padding: .8rem 1.2rem; margin: 1rem 0; }}
  details li {{ margin: .3rem 0; }}
  .formula {{ font-family: ui-monospace, Menlo, monospace; background: #f0f4f6; padding: .6rem; border-radius: 4px; }}
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

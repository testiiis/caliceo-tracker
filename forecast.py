"""
Caliceo Lieusaint - Modèle prévisionnel et tendances
====================================================

Lit data.sqlite (en LECTURE SEULE) et produit dans output/ :
- prevision_semaine.png / .csv : affluence prévue heure par heure pour les
  7 prochains jours, avec un intervalle de prévision à 80 %
- affluence_par_mois.csv       : tableau mensuel
- tendances_saisons.csv        : tableau par saison (+ vacances / hors vacances)
- forecast_summary.json        : tout ce qu'affiche build_dashboard.py

Modèle (détails et hypothèses : README, section « Modèle prévisionnel ») :

    affluence(jour d, heure h) = μ + jour[w] + heure[h] + interaction[w,h]
                                 + β_vac_semaine · vacances(d) · semaine(d)
                                 + β_vac_weekend · vacances(d) · weekend(d)
                                 + β_férié · férié(d) + ε

Régression linéaire pondérée :
- poids exponentiellement décroissants avec l'ancienneté (demi-vie T),
- pénalité ridge (λ) sur les seules interactions jour×heure, qui ramène les
  cases peu mesurées vers le profil additif jour + heure.
T et λ sont choisis par backtest (validation sur les semaines passées).

Usage :
    python forecast.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analyze import AFFLUENCE_CMAP_STOPS, JOURS_FR
from calendrier import (
    SAISONS,
    VACANCES_CONNUES_JUSQU_AU,
    ferie_ou_pont,
    saison,
    vacances_scolaires,
)

DB_PATH = Path(__file__).parent / "data.sqlite"
OUTPUT_DIR = Path(__file__).parent / "output"
TZ_PARIS = ZoneInfo("Europe/Paris")

MOIS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet",
           "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
JOURS_COURTS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

SEUIL_CHARGE = 55        # % : seuil « chargé » déjà utilisé par la heatmap
HORIZON_JOURS = 7
BACKTEST_SEMAINES = 6
DEMI_VIES_SEMAINES = [4, 8, 16, None]   # None = pas de pondération temporelle
LAMBDAS = [1.0, 5.0, 20.0, 80.0]
QUANTILES_INTERVALLE = (0.10, 0.90)     # intervalle de prévision à 80 %


# --- Chargement et préparation ---------------------------------------------


def heures_ouverture(weekday: int) -> range:
    """Heures pleines d'ouverture (même règle que analyze.py / collect.yml)."""
    return range(10, 23) if weekday in (4, 5) else range(10, 22)


def load_slots() -> tuple[pd.DataFrame, list[str]]:
    """
    Retourne (créneaux, jours_de_fermeture).

    Un créneau = (date, heure) avec la moyenne des lectures de cette heure-là.
    """
    if not DB_PATH.exists():
        print(f"ERREUR : base introuvable ({DB_PATH}).")
        sys.exit(1)

    # mode=ro : la base n'est jamais modifiée par ce script.
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    raw = pd.read_sql_query(
        "SELECT timestamp, weekday, hour, attendance FROM attendance", conn
    )
    conn.close()
    if raw.empty:
        print("ERREUR : aucune donnée en base.")
        sys.exit(1)

    # Le timestamp est en heure de Paris : ses 10 premiers caractères donnent
    # la date locale (on évite la conversion UTC d'analyze.load_dataframe).
    raw["date"] = pd.to_datetime(raw["timestamp"].str[:10])

    ouvert = raw.apply(lambda r: r["hour"] in heures_ouverture(r["weekday"]), axis=1)
    raw = raw[ouvert]

    # Journées de fermeture : toutes les lectures du jour sont à 0 %.
    par_jour = raw.groupby("date")["attendance"].agg(["max", "count"])
    fermetures = par_jour[(par_jour["max"] == 0) & (par_jour["count"] >= 3)].index
    raw = raw[~raw["date"].isin(fermetures)]

    # Un 0 % isolé en pleine journée est une erreur de lecture (le site
    # affiche 0 % par défaut avant de charger la vraie valeur). À 10h, en
    # revanche, 0-3 % est courant à l'ouverture : on le garde.
    raw = raw[(raw["attendance"] > 0) | (raw["hour"] == 10)]

    slots = (
        raw.groupby(["date", "hour"], as_index=False)
        .agg(weekday=("weekday", "first"), attendance=("attendance", "mean"))
    )
    return enrich(slots), [d.strftime("%Y-%m-%d") for d in fermetures]


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les variables calendaires à partir de la colonne date."""
    df = df.copy()
    jours = df["date"].dt.date
    df["vacances"] = jours.map(lambda d: vacances_scolaires(d) is not None).astype(float)
    df["ferie"] = jours.map(lambda d: ferie_ou_pont(d) is not None).astype(float)
    df["saison"] = jours.map(saison)
    df["mois"] = df["date"].dt.to_period("M")
    return df


# --- Modèle -----------------------------------------------------------------


def design(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """
    Matrice de régression et masque des colonnes pénalisées (interactions).

    Colonnes : constante | jour (mar..dim) | heure (11..22) | jour×heure |
    vacances en semaine | vacances le week-end | férié.
    Lundi et 10h servent de référence. L'effet vacances est séparé entre
    semaine et week-end : les vacances libèrent surtout les journées de
    semaine (le week-end, les gens sont déjà libres).
    """
    n = len(df)
    w = df["weekday"].to_numpy()
    h = df["hour"].to_numpy()
    cols, penal = [np.ones(n)], [False]
    for j in range(1, 7):
        cols.append((w == j).astype(float)); penal.append(False)
    for hh in range(11, 23):
        cols.append((h == hh).astype(float)); penal.append(False)
    for j in range(7):
        for hh in heures_ouverture(j):
            cols.append(((w == j) & (h == hh)).astype(float)); penal.append(True)
    weekend = (w >= 5).astype(float)
    cols.append(df["vacances"].to_numpy() * (1 - weekend)); penal.append(False)
    cols.append(df["vacances"].to_numpy() * weekend); penal.append(False)
    cols.append(df["ferie"].to_numpy()); penal.append(False)
    return np.column_stack(cols), np.array(penal)


def poids_temporels(dates: pd.Series, reference: pd.Timestamp, demi_vie: int | None) -> np.ndarray:
    if demi_vie is None:
        return np.ones(len(dates))
    age_jours = (reference - dates).dt.days.to_numpy()
    return 0.5 ** (age_jours / (7 * demi_vie))


def fit(train: pd.DataFrame, demi_vie: int | None, lam: float) -> np.ndarray:
    """Moindres carrés pondérés + ridge sur les interactions (système augmenté)."""
    X, penal = design(train)
    y = train["attendance"].to_numpy()
    sw = np.sqrt(poids_temporels(train["date"], train["date"].max(), demi_vie))
    ridge = np.sqrt(lam) * np.eye(X.shape[1])[penal]
    # Pénalité infime sur les autres colonnes : évite un système singulier
    # quand une modalité est absente (ex. aucun jour férié dans l'historique).
    eps = 1e-3 * np.eye(X.shape[1])[~penal]
    A = np.vstack([X * sw[:, None], ridge, eps])
    b = np.concatenate([y * sw, np.zeros(len(ridge) + len(eps))])
    beta, *_ = np.linalg.lstsq(A, b, rcond=None)
    return beta


def predict(beta: np.ndarray, df: pd.DataFrame) -> np.ndarray:
    X, _ = design(df)
    return np.clip(X @ beta, 0, 100)


# --- Validation (backtest) --------------------------------------------------


def backtest(slots: pd.DataFrame) -> dict:
    """
    Validation « rolling origin » : pour chacune des N dernières semaines,
    on entraîne sur tout ce qui précède et on prévoit la semaine.
    Retourne le meilleur réglage, ses erreurs et la comparaison aux références.
    """
    fin = slots["date"].max()
    origines = [fin - pd.Timedelta(days=7 * k - 1) for k in range(BACKTEST_SEMAINES, 0, -1)]
    # Il faut au moins 4 semaines d'historique avant la première origine.
    origines = [o for o in origines if (o - slots["date"].min()).days >= 28]
    if not origines:
        return {}

    plis = []
    for o in origines:
        train = slots[slots["date"] < o]
        test = slots[(slots["date"] >= o) & (slots["date"] < o + pd.Timedelta(days=7))]
        if len(test):
            plis.append((train, test))

    resultats = []
    for dv in DEMI_VIES_SEMAINES:
        for lam in LAMBDAS:
            par_pli = [
                test["attendance"].to_numpy() - predict(fit(train, dv, lam), test)
                for train, test in plis
            ]
            residus = np.concatenate(par_pli)
            resultats.append({"demi_vie": dv, "lambda": lam, "par_pli": par_pli,
                              "mae": float(np.mean(np.abs(residus))), "residus": residus})
    best = min(resultats, key=lambda r: r["mae"])

    # Références naïves, évaluées sur les mêmes créneaux
    err_model, err_moy, err_s1 = [], [], []
    for train, test in plis:
        pred = predict(fit(train, best["demi_vie"], best["lambda"]), test)
        profil = train.groupby(["weekday", "hour"])["attendance"].mean()
        semaine_avant = train.set_index(["date", "hour"])["attendance"]
        for (_, r), p in zip(test.iterrows(), pred):
            ref_moy = profil.get((r["weekday"], r["hour"]), train["attendance"].mean())
            ref_s1 = semaine_avant.get((r["date"] - pd.Timedelta(days=7), r["hour"]))
            if ref_s1 is None:
                continue  # comparaison uniquement là où les 3 méthodes existent
            err_model.append(r["attendance"] - p)
            err_moy.append(r["attendance"] - ref_moy)
            err_s1.append(r["attendance"] - ref_s1)

    def mae(e): return round(float(np.mean(np.abs(e))), 1) if e else None
    def rmse(e): return round(float(np.sqrt(np.mean(np.square(e)))), 1) if e else None

    q_bas, q_haut = np.quantile(best["residus"], QUANTILES_INTERVALLE)
    # Couverture honnête de l'intervalle : pour chaque semaine testée,
    # l'intervalle est construit avec les erreurs des AUTRES semaines.
    dedans = []
    for i, r in enumerate(best["par_pli"]):
        autres = np.concatenate([x for j, x in enumerate(best["par_pli"]) if j != i])
        qb, qh = np.quantile(autres, QUANTILES_INTERVALLE)
        dedans.append((r >= qb) & (r <= qh))
    couverture = float(np.mean(np.concatenate(dedans)))
    return {
        "demi_vie_semaines": best["demi_vie"],
        "lambda": best["lambda"],
        "n_semaines": len(plis),
        "n_creneaux": int(len(best["residus"])),
        "n_creneaux_comparaison": len(err_model),
        "mae_tous_creneaux": round(best["mae"], 1),
        "biais": round(float(np.mean(best["residus"])), 1),
        "mae": {"modele": mae(err_model), "moyenne_creneau": mae(err_moy),
                "semaine_precedente": mae(err_s1)},
        "rmse": {"modele": rmse(err_model), "moyenne_creneau": rmse(err_moy),
                 "semaine_precedente": rmse(err_s1)},
        "q_bas": float(q_bas),
        "q_haut": float(q_haut),
        "couverture": round(couverture * 100),
    }


# --- Prévision --------------------------------------------------------------


def future_slots(debut: date) -> pd.DataFrame:
    rows = []
    for k in range(HORIZON_JOURS):
        d = debut + timedelta(days=k)
        for h in heures_ouverture(d.weekday()):
            rows.append({"date": pd.Timestamp(d), "hour": h, "weekday": d.weekday()})
    return enrich(pd.DataFrame(rows))


def forecast(slots: pd.DataFrame, bt: dict) -> tuple[pd.DataFrame, dict]:
    demi_vie = bt.get("demi_vie_semaines", 8)
    lam = bt.get("lambda", 20.0)
    beta = fit(slots, demi_vie, lam)

    maintenant = datetime.now(TZ_PARIS)
    # Après la fermeture, la « semaine à venir » commence le lendemain.
    debut = maintenant.date() + timedelta(days=1 if maintenant.hour >= 22 else 0)
    fut = future_slots(debut)
    fut["prevision"] = predict(beta, fut)

    # Sans backtest (historique trop court) : intervalle ± 1,28 écart-type
    # des résidus d'entraînement (approximation normale).
    if bt:
        q_bas, q_haut = bt["q_bas"], bt["q_haut"]
    else:
        s = float(np.std(slots["attendance"] - predict(beta, slots)))
        q_bas, q_haut = -1.28 * s, 1.28 * s
    fut["bas"] = np.clip(fut["prevision"] + q_bas, 0, 100)
    fut["haut"] = np.clip(fut["prevision"] + q_haut, 0, 100)

    coefs = {"vacances_semaine": round(float(beta[-3]), 1),
             "vacances_weekend": round(float(beta[-2]), 1),
             "ferie": round(float(beta[-1]), 1)}
    return fut, {"debut": debut, "coefs": coefs}


def plot_forecast(fut: pd.DataFrame, path: Path) -> None:
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("affluence", AFFLUENCE_CMAP_STOPS, N=256)
    jours = sorted(fut["date"].unique())
    heures = list(range(10, 23))
    grid = np.full((len(jours), len(heures)), np.nan)
    for _, r in fut.iterrows():
        grid[jours.index(r["date"]), heures.index(r["hour"])] = r["prevision"]

    labels = []
    for d in jours:
        d = pd.Timestamp(d).date()
        lab = f"{JOURS_COURTS[d.weekday()]} {d:%d/%m}"
        if ferie_ou_pont(d):
            lab += " ★"
        if vacances_scolaires(d):
            lab += " (vac.)"
        labels.append(lab)

    fig, ax = plt.subplots(figsize=(13, 4.8))
    im = ax.imshow(grid, aspect="auto", cmap=cmap, vmin=0, vmax=100)
    ax.set_xticks(range(len(heures)))
    ax.set_xticklabels([f"{h}h" for h in heures])
    ax.set_yticks(range(len(jours)))
    ax.set_yticklabels(labels)
    ax.set_title("Affluence prévue (%) — 7 prochains jours")
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            v = grid[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                        color="white" if v >= 45 else "black",
                        fontsize=9, fontweight="bold")
    cbar = fig.colorbar(im, ax=ax, ticks=[0, 20, 35, 45, 55, 70, 100])
    cbar.set_label("Affluence prévue (%)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"  - Prévision (heatmap) : {path}")


def resume_par_jour(fut: pd.DataFrame) -> list[dict]:
    out = []
    for d, g in fut.groupby("date"):
        d = pd.Timestamp(d).date()
        calme = g.loc[g["prevision"].idxmin()]
        pic = g.loc[g["prevision"].idxmax()]
        out.append({
            "date": d.isoformat(),
            "jour": f"{JOURS_FR[d.weekday()]} {d:%d/%m}",
            "moyenne": round(float(g["prevision"].mean())),
            "creneau_calme": f"{int(calme['hour'])}h",
            "creneau_calme_val": round(float(calme["prevision"])),
            "pic": f"{int(pic['hour'])}h",
            "pic_val": round(float(pic["prevision"])),
            "pic_haut": round(float(pic["haut"])),
            "ferie": ferie_ou_pont(d),
            "vacances": vacances_scolaires(d),
            "calendrier_inconnu": d > VACANCES_CONNUES_JUSQU_AU,
        })
    return out


# --- Tableaux mensuel et saisonnier -----------------------------------------


def ajouter_ecart_profil(slots: pd.DataFrame) -> pd.DataFrame:
    """
    Écart de chaque créneau au profil moyen jour×heure (toute la période).
    La moyenne de ces écarts sur un mois indique si ce mois était plus ou
    moins chargé QU'ATTENDU vu les créneaux effectivement mesurés : elle
    corrige le biais de couverture (heures manquantes, doublons).
    """
    slots = slots.copy()
    profil = slots.groupby(["weekday", "hour"])["attendance"].transform("mean")
    slots["ecart"] = slots["attendance"] - profil
    return slots


def stats_groupe(g: pd.DataFrame, moyenne_globale: float) -> dict:
    par_jour = g.groupby("weekday")["attendance"].mean()
    par_heure = g.groupby("hour")["attendance"].mean()
    semaine = g[g["weekday"] < 5]["attendance"]
    weekend = g[g["weekday"] >= 5]["attendance"]
    return {
        "debut": g["date"].min().strftime("%d/%m/%Y"),
        "fin": g["date"].max().strftime("%d/%m/%Y"),
        "jours": int(g["date"].nunique()),
        "creneaux": int(len(g)),
        "moyenne_brute": round(float(g["attendance"].mean()), 1),
        "moyenne_ajustee": round(moyenne_globale + float(g["ecart"].mean()), 1),
        "mediane": round(float(g["attendance"].median()), 1),
        "max": round(float(g["attendance"].max())),
        "pct_charges": round(100 * float((g["attendance"] >= SEUIL_CHARGE).mean())),
        "semaine": round(float(semaine.mean()), 1) if len(semaine) else None,
        "weekend": round(float(weekend.mean()), 1) if len(weekend) else None,
        "jour_pointe": JOURS_FR[int(par_jour.idxmax())],
        "heure_pointe": f"{int(par_heure.idxmax())}h",
    }


def tableau_mois(slots: pd.DataFrame) -> list[dict]:
    m_glob = float(slots["attendance"].mean())
    lignes, prec = [], None
    for mois, g in slots.groupby("mois"):
        s = stats_groupe(g, m_glob)
        s["mois"] = f"{MOIS_FR[mois.month - 1]} {mois.year}"
        s["partiel"] = s["jours"] < mois.days_in_month
        s["evolution"] = None if prec is None else round(s["moyenne_ajustee"] - prec, 1)
        prec = s["moyenne_ajustee"]
        lignes.append(s)
    return lignes


def tableau_saisons(slots: pd.DataFrame) -> list[dict]:
    m_glob = float(slots["attendance"].mean())
    derniere = slots["date"].max().date()
    lignes = []
    for nom in SAISONS:
        g = slots[slots["saison"] == nom]
        if g.empty:
            lignes.append({"groupe": nom, "vide": True})
            continue
        s = stats_groupe(g, m_glob)
        s.update(groupe=nom, vide=False,
                 en_cours=saison(derniere) == nom,
                 ecart_global=round(s["moyenne_ajustee"] - m_glob, 1))
        lignes.append(s)
    for nom, masque in (("Vacances scolaires (zone C)", slots["vacances"] == 1),
                        ("Hors vacances", slots["vacances"] == 0)):
        g = slots[masque]
        if g.empty:
            continue
        s = stats_groupe(g, m_glob)
        s.update(groupe=nom, vide=False, en_cours=False,
                 ecart_global=round(s["moyenne_ajustee"] - m_glob, 1))
        lignes.append(s)
    return lignes


# --- Main -------------------------------------------------------------------


def main() -> int:
    OUTPUT_DIR.mkdir(exist_ok=True)
    slots, fermetures = load_slots()
    print(f"{len(slots)} créneaux horaires exploitables "
          f"({slots['date'].nunique()} jours, fermetures exclues : {fermetures or 'aucune'}).")

    print("Backtest du modèle ...")
    bt = backtest(slots)
    if bt:
        print(f"  Réglage retenu : demi-vie={bt['demi_vie_semaines']} sem., λ={bt['lambda']}")
        print(f"  MAE modèle={bt['mae']['modele']} | moyenne créneau={bt['mae']['moyenne_creneau']}"
              f" | semaine précédente={bt['mae']['semaine_precedente']} (points de %)")
        print(f"  Couverture de l'intervalle 80 % : {bt['couverture']} %")

    fut, info = forecast(slots, bt)
    print(f"Prévision du {info['debut']:%d/%m/%Y} sur {HORIZON_JOURS} jours. Effets : {info['coefs']}")

    plot_forecast(fut, OUTPUT_DIR / "prevision_semaine.png")
    export = fut.assign(
        date=fut["date"].dt.strftime("%Y-%m-%d"),
        jour=fut["weekday"].map(lambda x: JOURS_FR[x]),
        heure=fut["hour"],
        prevision=fut["prevision"].round(1),
        borne_basse_80=fut["bas"].round(1),
        borne_haute_80=fut["haut"].round(1),
    )[["date", "jour", "heure", "prevision", "borne_basse_80", "borne_haute_80"]]
    export.to_csv(OUTPUT_DIR / "prevision_semaine.csv", index=False, encoding="utf-8")

    slots = ajouter_ecart_profil(slots)
    mois = tableau_mois(slots)
    saisons = tableau_saisons(slots)
    pd.DataFrame(mois).to_csv(OUTPUT_DIR / "affluence_par_mois.csv", index=False, encoding="utf-8")
    pd.DataFrame(saisons).to_csv(OUTPUT_DIR / "tendances_saisons.csv", index=False, encoding="utf-8")
    print("  - Tableaux CSV : affluence_par_mois.csv, tendances_saisons.csv")

    bt_json = {k: v for k, v in bt.items() if k not in ("q_bas", "q_haut")}
    if bt:
        bt_json["intervalle"] = [round(bt["q_bas"], 1), round(bt["q_haut"], 1)]
    summary = {
        "genere_le": datetime.now(TZ_PARIS).isoformat(timespec="minutes"),
        "debut": info["debut"].isoformat(),
        "jours": resume_par_jour(fut),
        "coefs": info["coefs"],
        "backtest": bt_json,
        "moyenne_globale": round(float(slots["attendance"].mean()), 1),
        "n_creneaux": int(len(slots)),
        "fermetures": fermetures,
        "mois": mois,
        "saisons": saisons,
    }
    (OUTPUT_DIR / "forecast_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("  - Résumé JSON : forecast_summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

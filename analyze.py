"""
Caliceo Lieusaint - Analyse et visualisation
============================================

Lit les données collectées dans data.sqlite et génère :
- une heatmap jour de la semaine x heure (moyenne d'affluence)
- une courbe d'affluence moyenne par heure (toutes les semaines confondues)
- une courbe d'affluence moyenne par jour de la semaine
- un récapitulatif statistique (CSV) avec min, max, moyenne, médiane par créneau
- un export CSV brut de toutes les mesures

Tous les fichiers sont écrits dans le sous-dossier `output/`.

Usage :
    python analyze.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DB_PATH = Path(__file__).parent / "data.sqlite"
OUTPUT_DIR = Path(__file__).parent / "output"

JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def load_dataframe() -> pd.DataFrame:
    if not DB_PATH.exists():
        print(f"ERREUR : base introuvable ({DB_PATH}). Lancez d'abord collect.py.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        """
        SELECT timestamp, weekday, hour, minute, attendance
        FROM attendance
        ORDER BY timestamp
        """,
        conn,
    )
    conn.close()

    # Parsing robuste des timestamps (tolère avec ou sans timezone)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")

    if df.empty:
        print("ERREUR : aucune donnée en base. Lancez d'abord collect.py.")
        sys.exit(1)

    # Filtrer les valeurs à 0% qui correspondent aux heures de fermeture
    # (le site affiche 0% hors horaires d'ouverture).
    # On garde seulement les créneaux 10h-22h en semaine et 10h-23h ven/sam.
    def is_open(row: pd.Series) -> bool:
        wd, h = row["weekday"], row["hour"]
        if wd in (4, 5):  # vendredi, samedi : 10h-23h
            return 10 <= h <= 22
        return 10 <= h <= 21  # autres jours : 10h-22h

    df["is_open"] = df.apply(is_open, axis=1)
    df["jour"] = df["weekday"].map(lambda x: JOURS_FR[x])
    return df


def heatmap_weekday_hour(df: pd.DataFrame, path: Path) -> None:
    """Heatmap moyenne d'affluence par (jour de semaine, heure)."""
    open_df = df[df["is_open"]].copy()
    if open_df.empty:
        print("Pas assez de données ouvertes pour la heatmap.")
        return

    pivot = (
        open_df.pivot_table(
            index="weekday", columns="hour", values="attendance", aggfunc="mean"
        )
        .reindex(index=range(7), columns=range(10, 24))
    )

    fig, ax = plt.subplots(figsize=(13, 5.5))
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn_r", vmin=0, vmax=100)

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{h}h" for h in pivot.columns])
    ax.set_yticks(range(7))
    ax.set_yticklabels(JOURS_FR)
    ax.set_xlabel("Heure")
    ax.set_ylabel("Jour de la semaine")
    ax.set_title("Affluence moyenne (%) — Caliceo Lieusaint")

    # Annotations dans les cases
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.values[i, j]
            if not np.isnan(v):
                ax.text(
                    j, i, f"{v:.0f}",
                    ha="center", va="center",
                    color="white" if v > 55 else "black",
                    fontsize=9,
                )

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Affluence moyenne (%)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"  - Heatmap : {path}")


def plot_avg_by_hour(df: pd.DataFrame, path: Path) -> None:
    open_df = df[df["is_open"]].copy()
    if open_df.empty:
        return

    g = open_df.groupby("hour")["attendance"].agg(["mean", "min", "max", "count"])

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.fill_between(g.index, g["min"], g["max"], alpha=0.2, label="Plage min-max")
    ax.plot(g.index, g["mean"], marker="o", linewidth=2, label="Moyenne")
    ax.set_xlabel("Heure de la journée")
    ax.set_ylabel("Affluence (%)")
    ax.set_title("Affluence moyenne par heure (tous jours confondus)")
    ax.set_xticks(range(10, 24))
    ax.set_xticklabels([f"{h}h" for h in range(10, 24)])
    ax.set_ylim(0, 105)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"  - Courbe par heure : {path}")


def plot_avg_by_weekday(df: pd.DataFrame, path: Path) -> None:
    open_df = df[df["is_open"]].copy()
    if open_df.empty:
        return

    g = open_df.groupby("weekday")["attendance"].mean().reindex(range(7))

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(JOURS_FR, g.values, color="#3a86ff")
    ax.set_ylabel("Affluence moyenne (%)")
    ax.set_title("Affluence moyenne par jour de la semaine")
    ax.set_ylim(0, max(100, g.max() * 1.1) if g.notna().any() else 100)
    ax.grid(True, axis="y", alpha=0.3)
    for bar, val in zip(bars, g.values):
        if not np.isnan(val):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1,
                f"{val:.1f}%",
                ha="center",
                fontsize=10,
            )
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"  - Barres par jour : {path}")


def plot_timeline(df: pd.DataFrame, path: Path) -> None:
    """Série temporelle complète, utile pour repérer les anomalies."""
    fig, ax = plt.subplots(figsize=(14, 4.5))
    ax.plot(df["timestamp"], df["attendance"], linewidth=0.7)
    ax.set_xlabel("Date")
    ax.set_ylabel("Affluence (%)")
    ax.set_title("Affluence dans le temps (toutes mesures, brut)")
    ax.set_ylim(0, 105)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"  - Timeline : {path}")


def export_stats_csv(df: pd.DataFrame, path: Path) -> None:
    open_df = df[df["is_open"]].copy()
    if open_df.empty:
        return
    stats = (
        open_df.groupby(["weekday", "jour", "hour"])["attendance"]
        .agg(["count", "mean", "median", "min", "max", "std"])
        .round(2)
        .reset_index()
        .rename(
            columns={
                "weekday": "jour_num",
                "count": "n_mesures",
                "mean": "moyenne",
                "median": "mediane",
                "std": "ecart_type",
            }
        )
    )
    stats.to_csv(path, index=False, encoding="utf-8")
    print(f"  - Stats CSV : {path}")


def export_raw_csv(df: pd.DataFrame, path: Path) -> None:
    df.drop(columns=["is_open"]).to_csv(path, index=False, encoding="utf-8")
    print(f"  - Données brutes CSV : {path}")


def print_summary(df: pd.DataFrame) -> None:
    print("\n" + "=" * 60)
    print("RÉSUMÉ")
    print("=" * 60)
    print(f"Mesures totales       : {len(df)}")
    print(f"Période               : {df['timestamp'].min()}  →  {df['timestamp'].max()}")
    open_df = df[df["is_open"]]
    print(f"Mesures aux heures d'ouverture : {len(open_df)}")
    if not open_df.empty:
        print(f"Affluence moyenne     : {open_df['attendance'].mean():.1f}%")
        print(f"Affluence médiane     : {open_df['attendance'].median():.1f}%")
        print(f"Affluence max         : {open_df['attendance'].max()}%")

        # Créneau le plus calme et le plus chargé
        creneaux = (
            open_df.groupby(["weekday", "hour"])["attendance"]
            .mean()
            .sort_values()
        )
        if len(creneaux) > 0:
            wd_min, h_min = creneaux.index[0]
            wd_max, h_max = creneaux.index[-1]
            print(
                f"Créneau le + calme   : {JOURS_FR[wd_min]} {h_min}h "
                f"(moy {creneaux.iloc[0]:.1f}%)"
            )
            print(
                f"Créneau le + chargé  : {JOURS_FR[wd_max]} {h_max}h "
                f"(moy {creneaux.iloc[-1]:.1f}%)"
            )
    print("=" * 60 + "\n")


def main() -> int:
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"Lecture de la base : {DB_PATH}")
    df = load_dataframe()
    print(f"{len(df)} mesures chargées.\n")

    print("Génération des sorties dans output/ :")
    heatmap_weekday_hour(df, OUTPUT_DIR / "heatmap_jour_heure.png")
    plot_avg_by_hour(df, OUTPUT_DIR / "moyenne_par_heure.png")
    plot_avg_by_weekday(df, OUTPUT_DIR / "moyenne_par_jour.png")
    plot_timeline(df, OUTPUT_DIR / "timeline_brute.png")
    export_stats_csv(df, OUTPUT_DIR / "statistiques_par_creneau.csv")
    export_raw_csv(df, OUTPUT_DIR / "donnees_brutes.csv")

    print_summary(df)
    return 0


if __name__ == "__main__":
    sys.exit(main())

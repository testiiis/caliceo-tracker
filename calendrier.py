"""
Calendrier utilisé par le modèle prévisionnel (forecast.py)
===========================================================

- Vacances scolaires zone C (Paris / Créteil / Versailles)
- Jours fériés français + ponts
- Saisons astronomiques

⚠️ Les vacances scolaires sont codées en dur pour ne dépendre d'aucun
service externe pendant la génération du tableau de bord.
Source : https://data.education.gouv.fr (jeu « fr-en-calendrier-scolaire »).
À METTRE À JOUR chaque année scolaire (ajouter une ligne par période).
"""

from __future__ import annotations

from datetime import date, timedelta

# Premier jour sans école → dernier jour avant la reprise (inclus).
VACANCES_ZONE_C: list[tuple[date, date, str]] = [
    # 2025-2026
    (date(2025, 10, 18), date(2025, 11, 2), "Toussaint"),
    (date(2025, 12, 20), date(2026, 1, 4), "Noël"),
    (date(2026, 2, 21), date(2026, 3, 8), "Hiver"),
    (date(2026, 4, 18), date(2026, 5, 3), "Printemps"),
    (date(2026, 5, 14), date(2026, 5, 17), "Pont de l'Ascension"),
    (date(2026, 7, 4), date(2026, 8, 31), "Été"),
    # 2026-2027
    (date(2026, 10, 17), date(2026, 11, 1), "Toussaint"),
    (date(2026, 12, 19), date(2027, 1, 3), "Noël"),
    (date(2027, 2, 6), date(2027, 2, 21), "Hiver"),
    (date(2027, 4, 3), date(2027, 4, 18), "Printemps"),
    (date(2027, 7, 3), date(2027, 9, 1), "Été"),
]

# Dernière date pour laquelle le calendrier scolaire est connu.
VACANCES_CONNUES_JUSQU_AU = date(2027, 9, 1)


def vacances_scolaires(d: date) -> str | None:
    """Nom de la période de vacances (zone C) contenant d, sinon None."""
    for debut, fin, nom in VACANCES_ZONE_C:
        if debut <= d <= fin:
            return nom
    return None


def _paques(annee: int) -> date:
    """Dimanche de Pâques (algorithme de Meeus/Jones/Butcher, calendrier grégorien)."""
    a = annee % 19
    b, c = divmod(annee, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mois, jour = divmod(h + l - 7 * m + 114, 31)
    return date(annee, mois, jour + 1)


def jours_feries(annee: int) -> dict[date, str]:
    """Jours fériés nationaux en France métropolitaine."""
    p = _paques(annee)
    return {
        date(annee, 1, 1): "Jour de l'an",
        p + timedelta(days=1): "Lundi de Pâques",
        date(annee, 5, 1): "Fête du travail",
        date(annee, 5, 8): "Victoire 1945",
        p + timedelta(days=39): "Ascension",
        p + timedelta(days=50): "Lundi de Pentecôte",
        date(annee, 7, 14): "Fête nationale",
        date(annee, 8, 15): "Assomption",
        date(annee, 11, 1): "Toussaint",
        date(annee, 11, 11): "Armistice",
        date(annee, 12, 25): "Noël",
    }


def ferie_ou_pont(d: date) -> str | None:
    """
    Nom du jour férié, ou « Pont » si d est un lundi précédant un mardi
    férié ou un vendredi suivant un jeudi férié. Sinon None.
    """
    feries = jours_feries(d.year)
    if d in feries:
        return feries[d]
    if d.weekday() == 0 and d + timedelta(days=1) in feries:
        return "Pont"
    if d.weekday() == 4 and d - timedelta(days=1) in feries:
        return "Pont"
    return None


SAISONS = ["Printemps", "Été", "Automne", "Hiver"]


def saison(d: date) -> str:
    """Saison astronomique (dates de début arrondies : 20/03, 21/06, 22/09, 21/12)."""
    md = (d.month, d.day)
    if (3, 20) <= md < (6, 21):
        return "Printemps"
    if (6, 21) <= md < (9, 22):
        return "Été"
    if (9, 22) <= md < (12, 21):
        return "Automne"
    return "Hiver"

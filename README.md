# Caliceo Lieusaint — Tracker d'affluence (sans serveur)

Outil clé en main pour collecter automatiquement l'affluence du spa
**Caliceo Lieusaint** toutes les heures, **sans avoir besoin de garder ton
ordinateur allumé**, et visualiser les résultats dans une page web.

## Comment ça marche

```
┌─────────────────────────────────────────────────────────────┐
│ GitHub Actions (gratuit, exécute du code dans le cloud)     │
│                                                              │
│   ⏰ Toutes les heures                                       │
│      └─> collect.py va lire l'affluence sur le site         │
│         └─> sauvegarde dans data.sqlite (dans le repo)      │
│                                                              │
│   🌙 Tous les soirs                                          │
│      └─> analyze.py + build_dashboard.py                    │
│         └─> publie une page web sur GitHub Pages             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
        Tu consultes ta page web : https://TON-PSEUDO.github.io/caliceo-tracker
```

**Tout est gratuit et automatique. Tu n'as rien à faire après l'installation
(qui prend ~15 minutes).**

---

## 🚀 Installation pas à pas

### Étape 1 — Créer un compte GitHub (si tu n'en as pas)

Va sur https://github.com/signup et crée un compte gratuit.
Choisis un nom d'utilisateur que tu retiendras (par ex. `marie-dupont`).

### Étape 2 — Créer un repository (espace de stockage)

1. Connecté à GitHub, clique sur le **+** en haut à droite → **New repository**
2. Nom du repo : `caliceo-tracker` (ou autre, c'est toi qui choisis)
3. Coche **Public** (obligatoire pour avoir GitHub Actions et Pages gratuits)
4. **Ne coche rien d'autre** (pas de README, pas de .gitignore)
5. Clique **Create repository**

### Étape 3 — Uploader les fichiers du projet

Tu vois maintenant une page « Quick setup ». Clique sur le lien
**uploading an existing file**.

1. Décompresse le `.zip` que je t'ai fourni sur ton ordinateur.
2. **Sélectionne TOUS les fichiers et dossiers** à l'intérieur du dossier
   `caliceo_tracker` (donc `collect.py`, `analyze.py`, `build_dashboard.py`,
   `requirements.txt`, `README.md`, **et le dossier caché `.github`**).

   ⚠️ **Important** : sur Mac, active « Afficher les fichiers cachés »
   (Cmd + Shift + .) ou sur Windows (onglet Affichage → Éléments masqués)
   pour voir le dossier `.github`. Sinon GitHub Actions ne saura pas quoi faire.

3. Glisse-dépose tous les fichiers/dossiers dans la zone de la page GitHub.
4. Tout en bas, clique **Commit changes**.

### Étape 4 — Activer GitHub Actions

1. Dans ton repo, clique sur l'onglet **Actions** (en haut)
2. Si GitHub te demande de confirmer, clique **I understand my workflows, go ahead and enable them**
3. Tu vois deux workflows à gauche :
   - **Collecte affluence Caliceo**
   - **Publier le tableau de bord**

### Étape 5 — Premier test : lancer la collecte manuellement

1. Onglet **Actions** → clique sur **Collecte affluence Caliceo**
2. À droite, clique **Run workflow** → **Run workflow** (le bouton vert)
3. Attends 1-2 minutes, puis recharge la page
4. Tu dois voir une coche verte ✅ : la collecte a fonctionné
5. Vérifie : retourne dans **Code**, le fichier `data.sqlite` doit apparaître

À partir de maintenant, GitHub va lancer la collecte **toutes les heures
automatiquement**, même la nuit, même si ton PC est éteint.

### Étape 6 — Activer GitHub Pages (pour voir les graphiques)

1. Onglet **Settings** (Paramètres) du repo
2. Menu de gauche : **Pages**
3. Section **Build and deployment**, sous **Source**, choisis **GitHub Actions**

### Étape 7 — Premier test du dashboard

1. Onglet **Actions** → clique sur **Publier le tableau de bord**
2. **Run workflow** → **Run workflow**
3. Attends 1-2 minutes
4. Une fois la coche verte ✅, retourne dans **Settings → Pages** : tu verras
   l'URL de ton site (ex. `https://marie-dupont.github.io/caliceo-tracker/`)
5. Clique dessus, ton tableau de bord s'affiche !

C'est terminé. ✨

---

## 📊 Comment voir les résultats

**À tout moment, va sur l'URL fournie par GitHub Pages** (par exemple
`https://TON-PSEUDO.github.io/caliceo-tracker/`).

Tu y verras :
- Le **nombre de mesures** collectées
- Le créneau le plus calme et le plus chargé
- Une **heatmap** jour × heure (le graphique principal pour ton analyse)
- Les courbes par heure et par jour
- Des liens pour télécharger les **CSV** (données brutes + stats)

La page se met à jour automatiquement chaque soir, ou immédiatement après chaque
collecte (ça dépend de la charge GitHub, max 24h de délai).

---

## 📥 Récupérer les données brutes pour ton analyse contextuelle

Sur ta page web, en bas, tu as deux boutons de téléchargement :
- `donnees_brutes.csv` : toutes les mesures, ligne par ligne
- `statistiques_par_creneau.csv` : moyennes, médianes, etc. par créneau

Ouvre le CSV dans Excel ou Google Sheets et ajoute des colonnes :
- `vacances_scolaires` (oui/non — zone C pour la région parisienne)
- `jour_ferie`
- `evenement` (grève transports, météo extrême, événement local…)

Puis fais des tableaux croisés dynamiques pour comparer les périodes.

📅 **Calendrier vacances zone C** : https://www.education.gouv.fr/calendrier-scolaire

---

## ⏱️ Quand puis-je commencer à analyser ?

| Durée de collecte | Ce que tu peux dire |
|---|---|
| 1 semaine | Première idée des pics quotidiens |
| 2-3 semaines | Tendances par jour de la semaine fiables |
| 1 mois | Analyses solides + premières comparaisons (vacances vs hors vacances) |
| 3+ mois | Tendances saisonnières, événements ponctuels, etc. |

Le spa est ouvert 12h/jour, donc en 1 mois tu auras ~360 mesures exploitables.

---

## 🛠️ Utilisation locale (optionnelle)

Si tu veux régénérer les graphiques à la main sur ton ordinateur (par ex. après
avoir téléchargé `data.sqlite` depuis ton repo) :

```bash
pip install -r requirements.txt
playwright install chromium    # uniquement si tu veux aussi tester collect.py en local
python analyze.py              # génère les graphiques dans output/
python build_dashboard.py      # génère output/index.html
```

---

## 📁 Structure du projet

```
caliceo-tracker/
├── .github/
│   └── workflows/
│       ├── collect.yml         # Workflow de collecte (toutes les heures)
│       └── dashboard.yml       # Workflow de publication (tous les soirs)
├── collect.py                  # Script de collecte
├── analyze.py                  # Script d'analyse
├── build_dashboard.py          # Génère la page HTML
├── requirements.txt            # Dépendances Python
├── README.md                   # Ce fichier
└── data.sqlite                 # Base de données (créée automatiquement)
```

---

## ❓ FAQ et dépannage

**« GitHub Actions échoue à cause d'un quota »**
GitHub offre 2000 minutes/mois pour les comptes gratuits. Notre workflow utilise
~30 secondes par exécution × 24/jour × 30 jours = **~6 heures/mois**. Largement
sous le quota.

**« Mon repo doit absolument être public ? »**
Oui, sinon GitHub Actions et GitHub Pages sont payants. Ne mets aucune
information sensible dedans (mais comme on ne collecte que de l'affluence
publique, aucun souci).

**« Les graphiques sont vides »**
Tu n'as pas encore assez de données. Attends quelques jours et relance le
workflow « Publier le tableau de bord » manuellement.

**« L'heure semble décalée »**
Toutes les heures sont en **Europe/Paris** dans la base. Si tu vois des
décalages, c'est probablement le fuseau de ton tableur (Excel) qui réinterprète
le timestamp. Force le format texte sur la colonne `timestamp` lors de l'import.

**« Le site Caliceo a changé et la collecte échoue »**
Le scraper cherche le motif texte `Affluence en direct : X%`. Si Caliceo change
la formulation, modifie la regex dans `collect.py` (cherche `Affluence`).

**« Je veux collecter plus souvent (toutes les 30 min) »**
Dans `.github/workflows/collect.yml`, change `'5 * * * *'` en `'5,35 * * * *'`.
Reste raisonnable pour ne pas surcharger le site Caliceo.

**« Je veux supprimer le projet »**
Va dans **Settings** → tout en bas → **Delete this repository**. Toutes les
données sont supprimées.

---

## ⚖️ Limites & considérations

- **Mesure ponctuelle** : 1 valeur par heure (HH:05). Tu n'auras pas la
  granularité fine d'un pic à 12h47.
- **Respect du site** : 1 requête/heure est très léger.
- **Usage personnel** : pour analyse perso, pas de redistribution publique.
- **GitHub Actions peut avoir 5-10 min de retard** sur l'heure pile en cas de
  forte charge sur leurs serveurs. C'est normal et acceptable.

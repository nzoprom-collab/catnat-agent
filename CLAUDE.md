# CatNat Agent

Projet pour le hackathon **Nebius x NVIDIA** : rendu le **30/10/2026 à 18h**.
Piste **Best Apps and Agents**, avec le bonus **Tavily**.

**Objectif :** aider un particulier sinistré après une catastrophe naturelle.
1. Le radar détecte où en est sa commune : arrêté publié, demande de reconnaissance en cours, ou délai dépassé.
2. L'outil calcule la date limite de déclaration à l'assureur.
3. Il rédige la lettre de déclaration, à envoyer en recommandé avec AR.

**État actuel :** les étapes 1 à 5 sont terminées. Prochaine étape : l'interface.

## L'utilisateur

- Débutant, francophone. Toujours répondre en français et expliquer **simplement** chaque fichier, commande et choix.
- Dépôt public : https://github.com/nzoprom-collab/catnat-agent (licence MIT, exigée par le hackathon).
- Identité git propre à ce dépôt : `nzo <346365532+nzoprom-collab@users.noreply.github.com>`. C'est une adresse anonyme : ne jamais la remplacer par une vraie adresse mail.

## Fichiers

| Fichier | Rôle |
|---|---|
| `catnat.py` | Sans IA. `trouver_code_insee` (geo.api.gouv.fr), `recuperer_arretes_catnat` (API Géorisques `/api/v1/gaspar/catnat`), `calculer_delai_declaration` (date limite **prudente** = publication au JO + 29 jours ; la loi accorde 30 jours, art. L125-2 du Code des assurances), `simplifier` (enlève accents et ponctuation pour comparer des textes). |
| `llm.py` | `appeler_nemotron(messages, modele)` : **seul point d'appel à l'IA** (Nebius Token Factory, API compatible OpenAI). Additionne les tokens dans `usage.json` et refuse l'appel au-delà de `MAX_TOKENS_TOTAL`. |
| `lettre.py` | `generer_lettre(arrete, sinistre)` : l'IA rédige uniquement les 3 paragraphes du corps ; l'en-tête, l'objet, la politesse, « Pièce jointe » et la signature sont écrits par le code. Renvoie aussi une checklist des pièces à joindre, écrite par le code. |
| `radar.py` | `rechercher_actualites(commune, departement)` : 2 recherches Tavily, fusionnées sans doublons et mises en cache 24 h dans `cache/`. `analyser_situation(...)` : l'IA classe la situation en **A** (délai en cours), **B** (arrêté annoncé, pas encore dans Géorisques), **C** (demande de reconnaissance en cours), **E** (arrêté publié, délai dépassé) ou **D** (rien de récent). Priorité : A, B, C, E, D. |
| `hello.py` | Premier test de connexion à Nebius. Il appelle l'API directement, donc ses tokens ne sont **pas** comptés dans `usage.json`. |

**Tests** : lancer `.venv/bin/python <fichier>.py`.
- `catnat.py` : 3 communes.
- `lettre.py` : lettre fictive pour Gif-sur-Yvette.
- `radar.py` : Martigues, Saint-Aunès, Toulouse et Gif-sur-Yvette ; cas attendus C, C, E, D.

**Fichiers ignorés par git** : `.env`, `.venv/`, `usage.json`, `cache/`.

## Modèles (Nebius Token Factory)

- Base URL : `https://api.tokenfactory.nebius.com/v1`.
- `nvidia/nemotron-3-super-120b-a12b` : lettre et radar. Plus stable que Nano, qui a été comparé au radar à l'étape 5.
- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` : modèle par défaut de `llm.py` et de `hello.py`.

Ces modèles « réfléchissent » avant de répondre : le texte entre `<think>` et `</think>` est retiré par `llm.py`.

## Règles du projet (à respecter absolument)

1. **Ne jamais lire ni afficher `.env`.** Il contient `NEBIUS_API_KEY`, `TAVILY_API_KEY` et `MAX_TOKENS_TOTAL`.
   - Pour vérifier qu'une ligne existe : `grep -q` uniquement, qui ne montre rien.
   - Pour ajouter une ligne : l'écrire à la fin du fichier, sans toucher aux clés.
   - Dans un script lancé depuis le terminal : `load_dotenv("/home/nzo/catnat-agent/.env")`.
2. **L'IA n'invente jamais un fait.**
   - **Lettre** : l'IA écrit des étiquettes `{{COMMUNE}}`, `{{DATE_JO}}`… que le code remplace par les données de l'arrêté ou du sinistré. Une information manquante devient `[À COMPLÉTER]`. Le code refuse un brouillon s'il contient un chiffre ou un nom de mois inventé, s'il manque une étiquette ou un texte obligatoire, ou s'il n'a pas exactement 3 paragraphes.
   - **Radar** : seules les données Géorisques sont « officiel », et ces affirmations-là sont écrites par le code. Tout ce qui vient du web est « non officiel, à vérifier ». Chaque affirmation de l'IA doit donner une URL qui fait partie des résultats Tavily et une citation présente mot pour mot dans le résultat.
   - Le code a le dernier mot sur le cas :
     - A exige un arrêté dont le délai est en cours ;
     - B et C exigent une citation vérifiée, venant d'un site « officiel local » ou de « presse », qui nomme la commune (ou qui vient du site de cette mairie) ;
     - E exige un arrêté des 12 derniers mois dont le délai est dépassé.
   - Tous les **conseils** affichés à l'utilisateur sont écrits par le code, jamais par l'IA.
3. **Garde-fou de dépense** : tout appel à l'IA passe par `llm.appeler_nemotron`. Ne pas le contourner.
   - **Tavily** : 1 crédit par recherche de base, forfait de 1 000 crédits par mois. Utiliser le cache pour les tests.
4. **Toujours relire soi-même** ce que produit l'IA avant de dire que c'est bon, et signaler honnêtement ce qui ne marche pas.
5. **Faire un commit puis un push après chaque étape**, avec un message en français.

## Pièges connus

- **Tavily** :
  - une requête courte marche bien mieux qu'une phrase longue ;
  - `topic="news"` renvoie surtout de la presse américaine : utiliser `topic="general"` avec `country="france"` ;
  - les résultats varient d'un appel à l'autre ;
  - l'adresse `/usage` répond lentement et son compteur est en retard.
- **Saint-Aunès** reste classée D au lieu de C : la page de la mairie n'apparaît pas toujours dans les résultats de recherche.
- Un site de mairie au nom abrégé (par exemple `ville-gif.fr`) n'est pas reconnu comme « officiel local ».

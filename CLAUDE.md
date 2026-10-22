# 30 Days (dépôt `catnat-agent`)

Nom de l'appli : **30 Days**. Slogan : « Never miss your disaster claim deadline » (en français : « Ne ratez plus jamais votre délai de déclaration »). Le dépôt GitHub garde son nom `catnat-agent`.

Projet pour le hackathon **Nebius x NVIDIA** : rendu le **30/10/2026 à 18h**.
Piste **Best Apps and Agents**, avec le bonus **Tavily**.

**Objectif :** aider un particulier sinistré après une catastrophe naturelle.
1. Le radar détecte où en est sa commune : arrêté publié, demande de reconnaissance en cours, ou délai dépassé.
2. L'outil calcule la date limite de déclaration à l'assureur.
3. Il rédige la lettre de déclaration, à envoyer en recommandé avec AR.

**État actuel :** les étapes 1 à 7 sont terminées. L'étape 6 a ajouté l'inventaire à partir des photos, l'étape 7 l'interface web Streamlit « 30 Days » (`app.py`).

**Lancer l'appli :** `.venv/bin/streamlit run app.py`, puis ouvrir http://localhost:8501.

## L'utilisateur

- Débutant, francophone. Toujours répondre en français et expliquer **simplement** chaque fichier, commande et choix.
- Dépôt public : https://github.com/nzoprom-collab/catnat-agent (licence MIT, exigée par le hackathon).
- Identité git propre à ce dépôt : `nzo <346365532+nzoprom-collab@users.noreply.github.com>`. C'est une adresse anonyme : ne jamais la remplacer par une vraie adresse mail.

## Fichiers

| Fichier | Rôle |
|---|---|
| `catnat.py` | Sans IA. `trouver_code_insee` (geo.api.gouv.fr), `recuperer_arretes_catnat` (API Géorisques `/api/v1/gaspar/catnat`), `calculer_delai_declaration` (date limite **prudente** = publication au JO + 29 jours ; la loi accorde 30 jours, art. L125-2 du Code des assurances), `simplifier` (enlève accents et ponctuation pour comparer des textes). |
| `llm.py` | `appeler_nemotron(messages, modele, images=None)` : **seul point d'appel à l'IA** (Nebius Token Factory, API compatible OpenAI). Additionne les tokens dans `usage.json` et refuse l'appel au-delà de `MAX_TOKENS_TOTAL`. Les `images` (des chemins de fichiers) sont réduites à 1600 px maximum par `preparer_image`, puis envoyées en base64. |
| `photos.py` | `analyser_photos(chemins)` : un appel au modèle VL par photo, qui renvoie en JSON les dommages visibles (zone, objet, dommage, certitude « certain » ou « probable, à confirmer », numéro de photo). Le code vérifie chaque ligne : champs présents, numéro de photo existant, certitude connue, aucun prix ni valeur. La colonne « valeur estimée » reste à `[À COMPLÉTER]`. `inventaire_en_tableau` produit le tableau de l'annexe. |
| `lettre.py` | `generer_lettre(arrete, sinistre, inventaire=None)` : l'IA rédige uniquement les 3 paragraphes du corps, **en JSON** avec exactement 3 champs (`paragraphe_declaration`, `paragraphe_degats`, `paragraphe_demande`) ; un champ écrit sur plusieurs lignes est fusionné en un seul paragraphe ;  l'en-tête, l'objet, la politesse, les pièces jointes, la signature et l'annexe sont écrits par le code. Le paragraphe des dégâts fait **3 phrases maximum**, résumées par pièce, avec **un seul** renvoi à l'annexe (vérifié par le code). **Avec arrêté** (cas A ou E) : les faits viennent de l'arrêté. **Sans arrêté** (`arrete=None`, cas B, C ou D) : le type et les dates de l'événement viennent du sinistré (`type_evenement`, `date_debut`, `date_fin`) ; la lettre déclare « dès maintenant », et le code refuse les mots « reconnu » et « arrêté cité en objet ». Avec un événement d'un seul jour, la lettre écrit « le 20/10/2026 » et non « du … au … ». Renvoie aussi une checklist écrite par le code. **Ne lève jamais d'erreur à cause de l'IA** : après 3 essais refusés (ou si l'IA ne répond pas), `paragraphes_de_secours` écrit les 3 paragraphes à partir d'un modèle fixe (mêmes étiquettes, mots du sinistré, pièces de l'inventaire relu) et le résultat contient `secours=True` ; l'appli affiche alors discrètement « version simplifiée ». |
| `pdf.py` | `lettre_en_pdf(lettre, inventaire)` : PDF avec fpdf2 et la police DejaVu (`fonts/`, licence libre) pour les accents, « » et €. L'annexe est un vrai tableau, sur une page A4 en paysage. |
| `app.py` | Interface Streamlit « 30 Days » en 3 étapes : Ma commune (carte colorée par cas, grand compte à rebours pour le cas A, sources avec badges), Mes dégâts (photos, inventaire modifiable avec `st.data_editor`, bouton « J'ai relu » obligatoire), Ma lettre (formulaire, aperçu, PDF, checklist à cocher). Bouton de démo (Martigues et les 3 photos d'exemple, sinistré fictif), interface FR/EN (la lettre reste en français), panneau « Comment ça marche ». Les conseils restent écrits par le code (`conseil()` les traduit en anglais). |
| `.streamlit/config.toml` | Thème de couleurs, photos de 15 Mo maximum, bouton « Deploy » caché. |
| `exemples/` | 3 photos de test libres de droits (CC0, CC BY 2.0, CC BY 2.5), venant de Wikimedia Commons. Auteurs et licences : `exemples/CREDITS.md`. N'ajouter que des images dont la licence est claire, et mettre `CREDITS.md` à jour. |
| `radar.py` | `rechercher_actualites(commune, departement)` : 2 recherches Tavily, fusionnées sans doublons et mises en cache 24 h dans `cache/`. `analyser_situation(...)` : l'IA classe la situation en **A** (délai en cours), **B** (arrêté annoncé, pas encore dans Géorisques), **C** (demande de reconnaissance en cours), **E** (arrêté publié, délai dépassé) ou **D** (rien de récent). Priorité : A, B, C, E, D. |
| `hello.py` | Premier test de connexion à Nebius. Il appelle l'API directement, donc ses tokens ne sont **pas** comptés dans `usage.json`. |

**Tests** : lancer `.venv/bin/python <fichier>.py`.
- `catnat.py` : 3 communes.
- `lettre.py` : lettre fictive pour Gif-sur-Yvette.
- Lettre de la démo Martigues (avec l'inventaire des 3 photos), 5 fois de suite, le 22/10/2026 : 5 réussies sur 5, dont 4 du premier coup (1 en 2 essais, car le paragraphe des dégâts faisait 5 phrases) ; aucune lettre de secours ; environ 2 500 à 6 000 tokens par lettre (17 891 au total).
- Pour tester la lettre de secours sans dépenser de tokens : remplacer `lettre.appeler_nemotron` par une fonction qui lève une erreur.
- `radar.py` : Martigues, Saint-Aunès, Toulouse et Gif-sur-Yvette ; cas attendus C, C, E, D.
- `photos.py` : inventaire des 3 photos de `exemples/`, puis lettre complète avec l'annexe (environ 14 000 tokens).
- `app.py` : si l'appli tourne déjà sur le port 8501 dans un autre terminal, tester sur un autre port (`--server.port 8502`). Tester le parcours sans navigateur avec `streamlit.testing.v1.AppTest` (cliquer sur le bouton de démo, puis « Continuer », « Analyser mes 3 photos », « J'ai relu », « Générer »). Pour les captures d'écran : Chrome sans écran piloté par le protocole DevTools, avec `--remote-allow-origins`.

**Fichiers ignorés par git** : `.env`, `.venv/`, `usage.json`, `cache/`.

## Modèles (Nebius Token Factory)

- Base URL : `https://api.tokenfactory.nebius.com/v1`.
- `nvidia/nemotron-3-super-120b-a12b` : lettre et radar. Plus stable que Nano, qui a été comparé au radar à l'étape 5.
- `nvidia/Nemotron-3.5-Super-VL` : vision, utilisé pour l'inventaire photo. Il accepte les images au format OpenAI (`image_url` en base64) ; une photo de 1600 px coûte environ 3 000 à 4 000 tokens.
- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` : modèle par défaut de `llm.py` et de `hello.py`.

Ces modèles « réfléchissent » avant de répondre : le texte entre `<think>` et `</think>` est retiré par `llm.py`.

## Règles du projet (à respecter absolument)

1. **Ne jamais lire ni afficher `.env`.** Il contient `NEBIUS_API_KEY`, `TAVILY_API_KEY` et `MAX_TOKENS_TOTAL`.
   - Pour vérifier qu'une ligne existe : `grep -q` uniquement, qui ne montre rien.
   - Pour ajouter une ligne : l'écrire à la fin du fichier, sans toucher aux clés.
   - Dans un script lancé depuis le terminal : `load_dotenv("/home/nzo/catnat-agent/.env")`.
2. **L'IA n'invente jamais un fait.**
   - **Lettre** : l'IA écrit des étiquettes `{{COMMUNE}}`, `{{DATE_JO}}`… que le code remplace par les données de l'arrêté ou du sinistré. Une information manquante devient `[À COMPLÉTER]`. Le code refuse un brouillon s'il n'est pas un JSON avec les 3 champs, s'il contient un chiffre ou un nom de mois inventé, ou s'il manque une étiquette ou un texte obligatoire.
   - **Radar** : seules les données Géorisques sont « officiel », et ces affirmations-là sont écrites par le code. Tout ce qui vient du web est « non officiel, à vérifier ». Chaque affirmation de l'IA doit donner une URL qui fait partie des résultats Tavily et une citation présente mot pour mot dans le résultat.
   - Le code a le dernier mot sur le cas :
     - A exige un arrêté dont le délai est en cours ;
     - B et C exigent une citation vérifiée, venant d'un site « officiel local » ou de « presse », qui nomme la commune (ou qui vient du site de cette mairie) ;
     - E exige un arrêté des 12 derniers mois dont le délai est dépassé.
   - Tous les **conseils** affichés à l'utilisateur sont écrits par le code, jamais par l'IA.
   - **Photos** : seulement les dommages visibles et causés par l'eau, pas l'usure ancienne. Aucun prix, aucune valeur, aucune marque. L'inventaire est un brouillon que le sinistré doit relire, et l'annexe le dit.
3. **Garde-fou de dépense** : tout appel à l'IA passe par `llm.appeler_nemotron`. Ne pas le contourner.
   - **Interface** : limites par session (3 analyses de commune, 2 lettres, 6 photos ; les photos de démo ne comptent pas).
   - Mises en cache par `st.cache_data`, donc partagées entre visiteurs : le radar d'une commune (6 h) et l'analyse des photos de démo. Ce sont uniquement des données publiques.
   - **Jamais de cache pour les photos ou les informations d'un sinistré.** Les photos envoyées restent en mémoire (`UploadedFile`) et ne sont jamais écrites sur le disque.
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
- **Photos** : le modèle VL exagère parfois (« cuir détrempé », « terre répandue ») tout en marquant « certain ».
- **Lettre** :
  - le paragraphe des dégâts respecte les 3 phrases, mais ces phrases restent longues : l'IA y reprend presque tout l'inventaire ;
  - la consigne de prudence pour les dommages « probable, à confirmer » n'est pas toujours suivie, et le code ne peut pas le vérifier ;
  - l'IA recopie parfois une consigne mot pour mot dans la lettre (« sans les énumérer ») : formuler les consignes pour qu'elles ne puissent pas être recopiées telles quelles.
- **Les limites par session** se réinitialisent si on recharge la page : c'est une protection légère. Le vrai plafond reste `MAX_TOKENS_TOTAL`.

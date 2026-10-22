"""Radar CatNat : croise les données officielles (Géorisques) et l'actualité (Tavily) pour une commune.

Seules les données Géorisques sont « officiel » : ces affirmations-là sont écrites par le code.
Tout ce qui vient du web est « non officiel, à vérifier », avec un niveau de fiabilité selon le site.
L'IA classe la situation et cite ses sources web ; le code rejette toute affirmation dont la source
n'est pas un des résultats fournis, ne mentionne pas la commune, ou dont la citation n'existe pas.
"""

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv
from tavily import TavilyClient

from catnat import _format, calculer_delai_declaration, recuperer_arretes_catnat, simplifier, trouver_code_insee
from llm import appeler_nemotron

load_dotenv()

MODELE_RADAR = "nvidia/nemotron-3-super-120b-a12b"
SOURCE_GEORISQUES = "https://georisques.gouv.fr/api/v1/gaspar/catnat"
OFFICIEL = "officiel"
NON_OFFICIEL = "non officiel, à vérifier"

DOSSIER_CACHE = Path(__file__).parent / "cache"
DUREE_CACHE = timedelta(hours=24)

# Niveaux de fiabilité des sources web
OFFICIEL_LOCAL = "officiel local"
PRESSE = "presse"
RESEAU_SOCIAL = "réseau social"
AUTRE_SITE = "autre site"
NIVEAUX_FIABLES = {OFFICIEL_LOCAL, PRESSE}

SITES_PRESSE = [
    "ouest-france.fr", "laprovence.com", "ladepeche.fr", "midilibre.fr", "sudouest.fr", "leparisien.fr",
    "lavoixdunord.fr", "nicematin.com", "varmatin.com", "corsematin.com", "ledauphine.com", "actu.fr",
    "francebleu.fr", "ici.fr", "francetvinfo.fr", "franceinfo.fr", "letelegramme.fr", "maritima.fr",
    "lemonde.fr", "lefigaro.fr", "liberation.fr", "20minutes.fr", "bfmtv.com", "tf1info.fr", "lexpress.fr",
    "la-croix.com", "estrepublicain.fr", "dna.fr", "lalsace.fr", "leprogres.fr", "lamontagne.fr",
    "lanouvellerepublique.fr", "larepubliquedespyrenees.fr", "courrier-picard.fr", "paris-normandie.fr",
    "lunion.fr", "lindependant.fr", "objectifgard.com", "lagazettedescommunes.com",
]
SITES_RESEAUX_SOCIAUX = [
    "facebook.com", "fb.watch", "instagram.com", "x.com", "twitter.com", "tiktok.com", "youtube.com",
    "youtu.be", "linkedin.com", "threads.net", "threads.com", "snapchat.com", "pinterest.com", "reddit.com",
]
# Sites mis en avant par Tavily (les autres restent possibles, mais passent après)
SITES_PRIVILEGIES = ["gouv.fr", "legifrance.gouv.fr"] + SITES_PRESSE

CAS = {
    "A": "Arrêté officiel dans Géorisques, délai de déclaration en cours",
    "B": "Arrêté annoncé dans l'actualité, pas encore dans Géorisques",
    "C": "Demande de reconnaissance en cours, pas encore d'arrêté",
    "E": "Arrêté publié, délai de déclaration dépassé",
    "D": "Rien de récent",
}

CONSIGNES = f"""Tu analyses la situation « catastrophe naturelle » d'une commune française.
Tu reçois les arrêtés officiels de la base Géorisques et des résultats de recherche web récents.

Classe la situation dans UN SEUL cas :
A = un arrêté figure dans Géorisques et son délai de déclaration est en cours
B = un arrêté de reconnaissance pour un événement récent de cette commune est annoncé dans les
    résultats web, mais il ne figure pas dans la liste Géorisques
C = la mairie a déposé ou prépare une demande de reconnaissance, et aucun arrêté n'est encore publié
E = un arrêté Géorisques des douze derniers mois existe mais son délai de déclaration est dépassé
D = rien de récent concernant cette commune
Si plusieurs cas s'appliquent, choisis le premier dans l'ordre A, B, C, E, D.

Règles :
- Base-toi uniquement sur les documents fournis. N'invente rien.
- Un événement n'est récent que s'il a eu lieu après la date « récent depuis » indiquée. Les articles
  qui reparlent d'un événement plus ancien ne comptent pas.
- Chaque résultat web indique son type de source. Pour les cas B et C, appuie-toi sur des sources
  « officiel local » ou « presse » : un réseau social seul ne suffit pas.
- Les arrêtés Géorisques sont déjà affichés à l'utilisateur : ne les recopie pas dans tes affirmations.
- Tes affirmations portent sur les résultats web et servent à justifier le cas choisi (arrêté
  annoncé, demande de reconnaissance, événement récent). Chacune donne l'URL exacte du résultat et
  une citation : un morceau de phrase recopié mot pour mot depuis son titre ou son extrait.
  S'il n'y a rien d'utile sur le web, laisse la liste des affirmations vide.
- Écris en français.
- Réponds uniquement avec un objet JSON, sans texte autour, de cette forme :
{{"cas": "A", "explication": "deux phrases maximum", "affirmations": [{{"texte": "...", "citation": "...", "source": "URL"}}]}}"""

# Mot que doit contenir au moins une citation vérifiée et fiable pour que le cas soit accepté
MOT_EXIGE = {"B": "arrete", "C": "reconnaissance"}
LONGUEUR_MIN_CITATION = 20


def _domaine(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


def site_de_la_commune(url, commune):
    """Vrai si l'URL est le site de CETTE mairie (« saint-aunes.fr », « ville-martigues.fr »...)."""
    nom_commune = simplifier(commune).replace(" ", "-")
    base = _domaine(url).rsplit(".", 1)[0]
    if base.removeprefix("ville-").removeprefix("mairie-") in (nom_commune, nom_commune.replace("-", "")):
        return True
    # IntraMuros : application officielle des communes (une page par commune)
    return _domaine(url) == "intramuros.org" and urlparse(url).path.lower().startswith("/" + nom_commune)


def niveau_source(url, commune):
    """Classe un site : officiel local, presse, réseau social ou autre site."""
    domaine = _domaine(url)

    def est_sur(sites):
        return any(domaine == s or domaine.endswith("." + s) for s in sites)

    if est_sur(SITES_RESEAUX_SOCIAUX):
        return RESEAU_SOCIAL
    if domaine.endswith("gouv.fr") or site_de_la_commune(url, commune):  # État, préfectures, Légifrance, mairie
        return OFFICIEL_LOCAL
    if est_sur(SITES_PRESSE):
        return PRESSE
    return AUTRE_SITE


def _justifie(cas, affirmation, commune):
    """Une affirmation justifie le cas B ou C si elle vient d'une source fiable, contient le mot
    exigé, et parle bien de cette commune (dans la citation, ou parce que c'est le site de la mairie)."""
    citation = simplifier(affirmation.get("citation", ""))
    return (
        affirmation["statut"] == NON_OFFICIEL
        and affirmation["niveau"] in NIVEAUX_FIABLES
        and MOT_EXIGE[cas] in citation
        and (simplifier(commune) in citation or site_de_la_commune(affirmation["source"], commune))
    )


def rechercher_actualites(commune, departement):
    """Cherche sur le web les infos de moins de 3 mois sur une catastrophe naturelle dans la commune.

    Fait 2 recherches (demande de reconnaissance, arrêté), fusionne les résultats sans doublons et
    les garde 24 h dans cache/. Renvoie : resultats ({url, titre, contenu}), credits, requetes, depuis_cache.
    """
    lieu = f"{commune} {departement}" if departement else commune
    requetes = [
        f"{lieu} demande de reconnaissance catastrophe naturelle",
        f"{lieu} arrêté catastrophe naturelle",
    ]
    fichier_cache = DOSSIER_CACHE / f"{simplifier(lieu).replace(' ', '-')}.json"
    if fichier_cache.exists():
        cache = json.loads(fichier_cache.read_text())
        age = datetime.now() - datetime.fromisoformat(cache["date"])
        if cache["requetes"] == requetes and age < DUREE_CACHE:
            return {"resultats": cache["resultats"], "credits": 0, "requetes": requetes, "depuis_cache": True}

    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    resultats, urls_vues, credits = [], set(), 0
    for requete in requetes:
        reponse = client.search(
            requete,
            topic="general",
            country="france",
            start_date=(date.today() - timedelta(days=90)).isoformat(),
            max_results=20,  # le maximum ; une recherche coûte 1 crédit quel que soit ce nombre
            include_domains=SITES_PRIVILEGIES,
            include_domains_mode="prefer",
            include_usage=True,
            timeout=90,
        )
        credits += reponse.get("usage", {}).get("credits", 0)
        for r in reponse["results"]:
            cle = unquote(r["url"]).rstrip("/")
            if cle not in urls_vues:  # même page trouvée par les deux recherches : on la garde une fois
                urls_vues.add(cle)
                resultats.append({"url": r["url"], "titre": r.get("title", ""), "contenu": r.get("content", "")})

    DOSSIER_CACHE.mkdir(exist_ok=True)
    fichier_cache.write_text(json.dumps(
        {"date": datetime.now().isoformat(timespec="seconds"), "requetes": requetes, "resultats": resultats},
        ensure_ascii=False, indent=2,
    ))
    return {"resultats": resultats, "credits": credits, "requetes": requetes, "depuis_cache": False}


def _mentionne_commune(commune, resultat):
    return simplifier(commune) in simplifier(resultat["titre"] + " " + resultat["contenu"] + " " + resultat["url"])


def _affirmations_officielles(commune, recents):
    """Les affirmations « officiel » sont écrites par le code, directement depuis Géorisques."""
    if not recents:
        return [{"texte": f"Aucun arrêté CatNat publié au Journal officiel depuis un an pour {commune}.",
                 "source": SOURCE_GEORISQUES, "statut": OFFICIEL, "niveau": "Géorisques"}]
    affirmations = []
    for a in recents:
        if a["depasse"]:
            delai = f"délai dépassé depuis {-a['jours_restants']} jours"
        else:
            delai = f"délai en cours, {a['jours_restants']} jours restants"
        affirmations.append({
            "texte": f"Arrêté « {a['type']} » (événement du {_format(a['debut_evenement'])} au "
                     f"{_format(a['fin_evenement'])}) publié au JO le {_format(a['publication_jo'])} ; "
                     f"date limite de déclaration {_format(a['date_limite'])} : {delai}.",
            "source": SOURCE_GEORISQUES,
            "statut": OFFICIEL,
            "niveau": "Géorisques",
        })
    return affirmations


def _extraire_json(texte):
    """Récupère l'objet JSON dans la réponse de l'IA (elle ajoute parfois du texte autour)."""
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut == -1 or fin == -1:
        raise ValueError("aucun JSON dans la réponse")
    return json.loads(texte[debut:fin + 1])


def _conseil(cas, arretes_en_cours):
    """Conseil affiché à l'utilisateur, écrit par le code selon le cas."""
    if cas == "A":
        a = min(arretes_en_cours, key=lambda x: x["date_limite"])
        return (f"Déclarez vos dégâts à votre assureur, en recommandé avec AR, avant le "
                f"{_format(a['date_limite'])} ({a['jours_restants']} jours restants).")
    if cas == "B":
        return ("Un arrêté semble publié (non officiel, à vérifier sur legifrance.gouv.fr). Le délai de "
                "déclaration court dès la publication au Journal officiel : déclarez vos dégâts à "
                "votre assureur dès maintenant, sans attendre qu'il apparaisse dans Géorisques.")
    if cas == "C":
        return ("Déclarez vos dégâts à votre assureur dès maintenant, sans attendre l'arrêté. "
                "Signalez-les aussi à votre mairie pour appuyer sa demande de reconnaissance.")
    if cas == "E":
        return "Le délai légal est dépassé. Contactez votre assureur immédiatement en expliquant votre situation."
    return ("Aucune procédure récente détectée. En cas de dégâts, déclarez-les quand même à votre "
            "assureur et signalez-les à votre mairie, qui peut demander la reconnaissance.")


def analyser_situation(commune, arretes_georisques, resultats_tavily, modele=MODELE_RADAR):
    """Classe la situation de la commune (cas A, B, C, E ou D) à partir de Géorisques et du web.

    `arretes_georisques` : arrêtés renvoyés par recuperer_arretes_catnat().
    `resultats_tavily` : liste « resultats » renvoyée par rechercher_actualites().
    Renvoie un dictionnaire : cas, libelle, explication, conseil, affirmations, rejetees, corrections, tokens.
    """
    aujourd_hui = date.today()
    calcules = [calculer_delai_declaration(a, aujourd_hui) for a in arretes_georisques]
    recents = sorted(
        (a for a in calcules if a["publication_jo"] and a["publication_jo"] > aujourd_hui - timedelta(days=365)),
        key=lambda a: a["publication_jo"], reverse=True,
    )
    en_cours = [a for a in calcules if a["depasse"] is False]
    depasses_recents = [a for a in recents if a["depasse"]]
    # L'IA ne voit que les résultats web qui parlent de la commune : moins de bruit, moins d'erreurs
    pertinents = [r for r in resultats_tavily if _mentionne_commune(commune, r)]

    lignes_georisques = [
        f"- {a['type']} du {_format(a['debut_evenement'])} au {_format(a['fin_evenement'])}, "
        f"publié au JO le {_format(a['publication_jo'])}, date limite {_format(a['date_limite'])} : "
        + ("délai EN COURS" if not a["depasse"] else "délai dépassé")
        for a in recents
    ] or ["- Aucun arrêté publié au Journal officiel depuis un an."]
    lignes_web = [
        f"[{i}] URL : {r['url']}\nType de source : {niveau_source(r['url'], commune)}\n"
        f"Titre : {r['titre']}\nExtrait : {r['contenu'][:800]}"
        for i, r in enumerate(pertinents, start=1)
    ] or ["Aucun résultat."]
    message = (
        f"Date du jour : {_format(aujourd_hui)}\n"
        f"Récent depuis : {_format(aujourd_hui - timedelta(days=90))}\nCommune : {commune}\n\n"
        f"ARRÊTÉS GÉORISQUES DES DOUZE DERNIERS MOIS (source : {SOURCE_GEORISQUES}) :\n"
        + "\n".join(lignes_georisques)
        + "\n\nRÉSULTATS WEB (moins de trois mois) :\n" + "\n\n".join(lignes_web)
    )
    messages = [{"role": "system", "content": CONSIGNES}, {"role": "user", "content": message}]

    tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for essai in range(2):
        texte, tokens_appel = appeler_nemotron(messages, modele=modele, temperature=0, max_tokens=8000)
        for cle in tokens:
            tokens[cle] += tokens_appel[cle]
        try:
            analyse = _extraire_json(texte)
            break
        except ValueError:  # json.JSONDecodeError est aussi une ValueError
            if essai == 1:
                raise
            messages += [{"role": "assistant", "content": texte},
                         {"role": "user", "content": "Réponds uniquement avec l'objet JSON demandé."}]

    # 1. Vérifier les sources de l'IA : URL fournie, qui parle de la commune, citation recopiée à l'identique
    # unquote : « %C3%A9 » et « é » désignent la même URL, l'IA écrit parfois l'un pour l'autre
    resultats_par_url = {unquote(r["url"]): r for r in resultats_tavily}
    affirmations = _affirmations_officielles(commune, recents)
    rejetees = []
    for aff in analyse.get("affirmations", []):
        texte, source = aff.get("texte", ""), str(aff.get("source", "")).strip()
        citation = simplifier(str(aff.get("citation", "")))
        resultat = resultats_par_url.get(unquote(source))
        if resultat:
            source = resultat["url"]
        if source == SOURCE_GEORISQUES:
            raison = "les données Géorisques sont affichées par le code, pas par l'IA"
        elif resultat is None:
            raison = "cette URL ne fait pas partie des résultats Tavily"
        elif not _mentionne_commune(commune, resultat):
            raison = "ce résultat ne mentionne pas la commune"
        elif len(citation) < LONGUEUR_MIN_CITATION or citation not in simplifier(resultat["titre"] + " " + resultat["contenu"]):
            raison = "la citation ne figure pas mot pour mot dans le résultat"
        else:
            affirmations.append({"texte": texte, "citation": aff.get("citation", ""), "source": source,
                                 "statut": NON_OFFICIEL, "niveau": niveau_source(source, commune)})
            continue
        rejetees.append({"texte": texte, "source": source, "raison": raison})

    # 2. Vérifier la cohérence du cas avec les données (le code a le dernier mot)
    cas = str(analyse.get("cas", "D")).strip().upper()[:1]
    repli = "E" if depasses_recents else "D"  # cas retenu si celui de l'IA n'est pas justifié
    corrections = []
    if cas not in CAS:
        corrections.append(f"cas « {cas} » inconnu, remplacé par {repli}")
        cas = repli
    if en_cours:
        if cas != "A":
            corrections.append(f"cas {cas} remplacé par A : Géorisques contient un arrêté dont le délai est en cours")
            cas = "A"
    elif cas == "A":
        corrections.append(f"cas A impossible : aucun arrêté Géorisques avec délai en cours, remplacé par {repli}")
        cas = repli
    elif cas in MOT_EXIGE and not any(_justifie(cas, a, commune) for a in affirmations):
        corrections.append(f"cas {cas} remplacé par {repli} : aucune citation vérifiée d'un site officiel local "
                           f"ou de presse ne contient « {MOT_EXIGE[cas]} » en parlant de {commune}")
        cas = repli
    elif cas == "E" and not depasses_recents:
        corrections.append("cas E impossible : aucun arrêté Géorisques des douze derniers mois, remplacé par D")
        cas = "D"
    elif cas == "D" and depasses_recents:
        corrections.append("cas D remplacé par E : Géorisques contient un arrêté récent dont le délai est dépassé")
        cas = "E"

    explication = analyse.get("explication", "")
    if corrections:
        # L'explication de l'IA justifiait un autre cas : on ne l'affiche pas
        explication = "Analyse de l'IA écartée, car le code a corrigé le cas (voir ci-dessous)."

    return {
        "cas": cas,
        "libelle": CAS[cas],
        "explication": explication,
        "conseil": _conseil(cas, en_cours),
        "affirmations": affirmations,
        "rejetees": rejetees,
        "corrections": corrections,
        "tokens": tokens,
    }


if __name__ == "__main__":
    # (commune, département, cas attendu)
    communes_test = [
        ("Martigues", "13", "C"),       # demande de reconnaissance après les pluies du 20/10/2026
        ("Saint-Aunès", "34", "C"),     # demande de reconnaissance après les intempéries du 30/09/2026
        ("Toulouse", "31", "E"),        # arrêté publié au JO le 21/09/2026, délai dépassé
        ("Gif-sur-Yvette", "91", "D"),
    ]
    tableau = []

    for nom, departement, cas_attendu in communes_test:
        print("\n" + "=" * 78)
        try:
            code_insee, nom_officiel = trouver_code_insee(nom, code_departement=departement)
            print(f"{nom_officiel} ({departement}) – INSEE {code_insee}")
            arretes = recuperer_arretes_catnat(code_insee)
            recherche = rechercher_actualites(nom_officiel, departement)
            resultat = analyser_situation(nom_officiel, arretes, recherche["resultats"])
        except Exception as erreur:
            print(f"ERREUR : {erreur}")
            continue

        print(f"CAS {resultat['cas']} : {resultat['libelle']}  (attendu : {cas_attendu})")
        print(f"Explication (rédigée par l'IA) : {resultat['explication']}")
        print(f"Conseil : {resultat['conseil']}")
        print("Sources :")
        for a in resultat["affirmations"]:
            print(f"  [{a['statut']} · {a['niveau']}] {a['texte']}")
            if a.get("citation"):
                print(f"      citation : « {a['citation']} »")
            print(f"      -> {a['source']}")
        for a in resultat["rejetees"]:
            print(f"  [REJETÉE : {a['raison']}] {a['texte']}\n      -> {a['source'] or '(aucune source)'}")
        for c in resultat["corrections"]:
            print(f"  Correction du code : {c}")
        origine = "cache, 0 crédit" if recherche["depuis_cache"] else f"{recherche['credits']} crédit(s) Tavily"
        print(f"Coût : {resultat['tokens']['total_tokens']} tokens, {origine} "
              f"({len(recherche['resultats'])} résultats web uniques)")
        tableau.append((nom_officiel, resultat, cas_attendu, recherche))

    print("\n" + "=" * 78)
    print(f"{'Commune':<16} {'Trouvé':<7} {'Attendu':<8} {'Corr.':<6} {'Tokens':<7} {'Crédits':<8} Sources web retenues")
    for nom, resultat, cas_attendu, recherche in tableau:
        web = [f"{urlparse(a['source']).netloc.removeprefix('www.')} ({a['niveau']})"
               for a in resultat["affirmations"] if a["statut"] == NON_OFFICIEL]
        ok = "✓" if resultat["cas"] == cas_attendu else "✗"
        print(f"{nom:<16} {resultat['cas'] + ' ' + ok:<7} {cas_attendu:<8} {len(resultat['corrections']):<6} "
              f"{resultat['tokens']['total_tokens']:<7} {recherche['credits']:<8} {', '.join(web) or '—'}")
    print(f"TOTAL : {sum(r['tokens']['total_tokens'] for _, r, _, _ in tableau)} tokens, "
          f"{sum(rech['credits'] for *_, rech in tableau)} crédit(s) Tavily")

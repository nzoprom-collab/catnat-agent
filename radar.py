"""Radar CatNat : croise les données officielles (Géorisques) et l'actualité (Tavily) pour une commune.

Seules les données Géorisques sont « officiel » : ces affirmations-là sont écrites par le code.
Tout ce qui vient du web est « non officiel, à vérifier ». L'IA classe la situation et cite ses
sources web ; le code rejette toute affirmation dont la source n'est pas un des résultats fournis,
ou dont le résultat ne mentionne pas la commune.
"""

import json
import os
import re
import unicodedata
from datetime import date, timedelta
from urllib.parse import unquote

from dotenv import load_dotenv
from tavily import TavilyClient

from catnat import _format, calculer_delai_declaration, recuperer_arretes_catnat, trouver_code_insee
from llm import appeler_nemotron

load_dotenv()

MODELE_RADAR = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SOURCE_GEORISQUES = "https://georisques.gouv.fr/api/v1/gaspar/catnat"
OFFICIEL = "officiel"
NON_OFFICIEL = "non officiel, à vérifier"

# Sites mis en avant par Tavily (les autres restent possibles, mais passent après)
SITES_PRIVILEGIES = [
    "gouv.fr", "legifrance.gouv.fr",
    "ouest-france.fr", "laprovence.com", "ladepeche.fr", "midilibre.fr", "sudouest.fr",
    "leparisien.fr", "lavoixdunord.fr", "nicematin.com", "ledauphine.com", "actu.fr",
    "francebleu.fr", "france3-regions.francetvinfo.fr", "letelegramme.fr", "maritima.fr",
]

CAS = {
    "A": "Arrêté officiel dans Géorisques, délai de déclaration en cours",
    "B": "Arrêté annoncé dans l'actualité, pas encore dans Géorisques",
    "C": "Demande de reconnaissance en cours, pas encore d'arrêté",
    "D": "Rien de récent",
}

CONSIGNES = f"""Tu analyses la situation « catastrophe naturelle » d'une commune française.
Tu reçois les arrêtés officiels de la base Géorisques et des résultats de recherche web récents.

Classe la situation dans UN SEUL cas :
A = un arrêté figure dans Géorisques et son délai de déclaration est en cours
B = un arrêté de reconnaissance pour un événement récent de cette commune est annoncé dans les
    résultats web, mais il ne figure pas dans la liste Géorisques
C = la mairie a déposé ou prépare une demande de reconnaissance, et aucun arrêté n'est encore publié
D = rien de récent concernant cette commune
Si plusieurs cas s'appliquent, choisis le premier dans l'ordre A, B, C, D.

Règles :
- Base-toi uniquement sur les documents fournis. N'invente rien.
- Un événement n'est récent que s'il a eu lieu après la date « récent depuis » indiquée. Les articles
  qui reparlent d'un événement plus ancien ne comptent pas.
- Les arrêtés Géorisques sont déjà affichés à l'utilisateur : ne les recopie pas dans tes affirmations.
  Si un arrêté Géorisques récent a un délai dépassé, dis-le dans l'explication.
- Tes affirmations portent sur les résultats web et servent à justifier le cas choisi (arrêté
  annoncé, demande de reconnaissance, événement récent). Chacune donne l'URL exacte du résultat et
  une citation : un morceau de phrase recopié mot pour mot depuis son titre ou son extrait.
  S'il n'y a rien d'utile sur le web, laisse la liste des affirmations vide.
- Écris en français.
- Réponds uniquement avec un objet JSON, sans texte autour, de cette forme :
{{"cas": "A", "explication": "deux phrases maximum", "affirmations": [{{"texte": "...", "citation": "...", "source": "URL"}}]}}"""

# Mot que doit contenir au moins une citation vérifiée pour que le cas soit accepté
MOT_EXIGE = {"B": "arrete", "C": "reconnaissance"}
LONGUEUR_MIN_CITATION = 20


def rechercher_actualites(commune, departement):
    """Cherche sur le web les infos de moins de 3 mois sur une catastrophe naturelle dans la commune.

    Renvoie un dictionnaire : resultats (liste de {url, titre, contenu}), credits (coût Tavily), requete.
    """
    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    # Une requête courte donne de bien meilleurs résultats qu'une longue phrase. « reconnaissance »
    # couvre à la fois les demandes des mairies et les arrêtés (« arrêté portant reconnaissance... »)
    requete = f"{commune} {departement or ''} demande de reconnaissance catastrophe naturelle"
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
    resultats = [
        {"url": r["url"], "titre": r.get("title", ""), "contenu": r.get("content", "")}
        for r in reponse["results"]
    ]
    return {"resultats": resultats, "credits": reponse.get("usage", {}).get("credits", 0), "requete": requete}


def _simplifier(texte):
    """« Saint-Aunès » devient « saint aunes » : sans accents, tirets ni majuscules, pour comparer."""
    sans_accents = unicodedata.normalize("NFD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sans_accents.lower()).strip()


def _mentionne_commune(commune, resultat):
    return _simplifier(commune) in _simplifier(resultat["titre"] + " " + resultat["contenu"] + " " + resultat["url"])


def _affirmations_officielles(commune, recents):
    """Les affirmations « officiel » sont écrites par le code, directement depuis Géorisques."""
    if not recents:
        return [{"texte": f"Aucun arrêté CatNat publié au Journal officiel depuis un an pour {commune}.",
                 "source": SOURCE_GEORISQUES, "statut": OFFICIEL}]
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
    return ("Aucune procédure récente détectée. En cas de dégâts, déclarez-les quand même à votre "
            "assureur et signalez-les à votre mairie, qui peut demander la reconnaissance.")


def analyser_situation(commune, arretes_georisques, resultats_tavily):
    """Classe la situation de la commune (cas A, B, C ou D) à partir de Géorisques et du web.

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
    # L'IA ne voit que les résultats web qui parlent de la commune : moins de bruit, moins d'erreurs
    pertinents = [r for r in resultats_tavily if _mentionne_commune(commune, r)]

    lignes_georisques = [
        f"- {a['type']} du {_format(a['debut_evenement'])} au {_format(a['fin_evenement'])}, "
        f"publié au JO le {_format(a['publication_jo'])}, date limite {_format(a['date_limite'])} : "
        + ("délai EN COURS" if not a["depasse"] else "délai dépassé")
        for a in recents
    ] or ["- Aucun arrêté publié au Journal officiel depuis un an."]
    lignes_web = [
        f"[{i}] URL : {r['url']}\nTitre : {r['titre']}\nExtrait : {r['contenu'][:800]}"
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
        texte, tokens_appel = appeler_nemotron(messages, modele=MODELE_RADAR, temperature=0, max_tokens=4000)
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
        citation = _simplifier(str(aff.get("citation", "")))
        resultat = resultats_par_url.get(unquote(source))
        if resultat:
            source = resultat["url"]
        if source == SOURCE_GEORISQUES:
            raison = "les données Géorisques sont affichées par le code, pas par l'IA"
        elif resultat is None:
            raison = "cette URL ne fait pas partie des résultats Tavily"
        elif not _mentionne_commune(commune, resultat):
            raison = "ce résultat ne mentionne pas la commune"
        elif len(citation) < LONGUEUR_MIN_CITATION or citation not in _simplifier(resultat["titre"] + " " + resultat["contenu"]):
            raison = "la citation ne figure pas mot pour mot dans le résultat"
        else:
            affirmations.append({"texte": texte, "citation": aff.get("citation", ""),
                                 "source": source, "statut": NON_OFFICIEL})
            continue
        rejetees.append({"texte": texte, "source": source, "raison": raison})

    # 2. Vérifier la cohérence du cas avec les données (le code a le dernier mot)
    cas = str(analyse.get("cas", "D")).strip().upper()[:1]
    corrections = []
    if cas not in CAS:
        corrections.append(f"cas « {cas} » inconnu, remplacé par D")
        cas = "D"
    if en_cours and cas != "A":
        corrections.append(f"cas {cas} remplacé par A : Géorisques contient un arrêté dont le délai est en cours")
        cas = "A"
    elif cas == "A" and not en_cours:
        corrections.append("cas A impossible : aucun arrêté Géorisques avec délai en cours, remplacé par D")
        cas = "D"
    elif cas in MOT_EXIGE and not any(
        a["statut"] == NON_OFFICIEL and MOT_EXIGE[cas] in _simplifier(a["citation"]) for a in affirmations
    ):
        corrections.append(f"cas {cas} remplacé par D : aucune citation vérifiée ne contient "
                           f"« {MOT_EXIGE[cas]} »")
        cas = "D"

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
    communes_test = [
        ("Martigues", "13"),       # trouvée via Tavily : inondations du 20/10/2026
        ("Saint-Aunès", "34"),     # trouvée via Tavily : intempéries du 30/09/2026
        ("Toulouse", "31"),
        ("Gif-sur-Yvette", "91"),
    ]
    total_tokens, total_credits = 0, 0

    for nom, departement in communes_test:
        print("\n" + "=" * 78)
        try:
            code_insee, nom_officiel = trouver_code_insee(nom, code_departement=departement)
            print(f"{nom_officiel} ({departement}) – INSEE {code_insee}")
            arretes = recuperer_arretes_catnat(code_insee)
            recherche = rechercher_actualites(nom_officiel, departement)
            total_credits += recherche["credits"]
            resultat = analyser_situation(nom_officiel, arretes, recherche["resultats"])
        except Exception as erreur:
            print(f"ERREUR : {erreur}")
            continue
        total_tokens += resultat["tokens"]["total_tokens"]

        print(f"CAS {resultat['cas']} : {resultat['libelle']}")
        print(f"Explication (rédigée par l'IA) : {resultat['explication']}")
        print(f"Conseil : {resultat['conseil']}")
        print("Sources :")
        for a in resultat["affirmations"]:
            print(f"  [{a['statut']}] {a['texte']}")
            if a.get("citation"):
                print(f"      citation : « {a['citation']} »")
            print(f"      -> {a['source']}")
        if not resultat["affirmations"]:
            print("  (aucune)")
        for a in resultat["rejetees"]:
            print(f"  [REJETÉE : {a['raison']}] {a['texte']}\n      -> {a['source'] or '(aucune source)'}")
        for c in resultat["corrections"]:
            print(f"  Correction du code : {c}")
        print(f"Coût : {resultat['tokens']['total_tokens']} tokens, {recherche['credits']} crédit(s) Tavily "
              f"({len(recherche['resultats'])} résultats web)")

    print("\n" + "=" * 78)
    print(f"TOTAL : {total_tokens} tokens Nebius, {total_credits} crédit(s) Tavily")

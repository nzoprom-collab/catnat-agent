"""Arrêtés de catastrophe naturelle d'une commune, à partir des API publiques de l'État (sans IA)."""

import re
import unicodedata
from datetime import date, datetime, timedelta

import requests

GEO_API = "https://geo.api.gouv.fr/communes"
GEORISQUES_CATNAT_API = "https://georisques.gouv.fr/api/v1/gaspar/catnat"

# Le Code des assurances (art. L125-2) laisse 30 jours après la publication au JO.
# On compte 29 jours pour garder un jour de marge.
DELAI_PRUDENT_JOURS = 29


def trouver_code_insee(nom_commune, code_postal=None, code_departement=None):
    """Renvoie (code INSEE, nom officiel) d'une commune, via geo.api.gouv.fr."""
    params = {"nom": nom_commune, "fields": "nom,code", "boost": "population"}
    if code_postal:
        params["codePostal"] = code_postal
    if code_departement:
        params["codeDepartement"] = code_departement
    reponse = requests.get(GEO_API, params=params, timeout=20)
    reponse.raise_for_status()
    communes = reponse.json()
    if not communes:
        raise ValueError(f"Commune introuvable : {nom_commune} {code_postal or ''}".strip())
    # Sans code postal, plusieurs communes peuvent porter le même nom :
    # grâce à boost=population, la première est la plus peuplée.
    return communes[0]["code"], communes[0]["nom"]


def recuperer_arretes_catnat(code_insee):
    """Renvoie la liste de tous les arrêtés CatNat d'une commune, via l'API Géorisques."""
    arretes = []
    page = 1
    while True:
        params = {"code_insee": code_insee, "page": page, "page_size": 100}
        reponse = requests.get(GEORISQUES_CATNAT_API, params=params, timeout=30)
        reponse.raise_for_status()
        contenu = reponse.json()
        arretes.extend(contenu["data"])
        if page >= contenu["total_pages"]:
            return arretes
        page += 1


def _lire_date(texte):
    """Transforme "17/12/2000" en date Python (ou None si le champ est vide)."""
    return datetime.strptime(texte, "%d/%m/%Y").date() if texte else None


def calculer_delai_declaration(arrete, aujourd_hui=None):
    """Ajoute à un arrêté sa date limite de déclaration, les jours restants et si c'est dépassé."""
    aujourd_hui = aujourd_hui or date.today()
    date_jo = _lire_date(arrete.get("date_publication_jo"))
    resultat = {
        "type": arrete.get("libelle_risque_jo"),
        "debut_evenement": _lire_date(arrete.get("date_debut_evt")),
        "fin_evenement": _lire_date(arrete.get("date_fin_evt")),
        "publication_jo": date_jo,
        "date_limite": None,
        "jours_restants": None,
        "depasse": None,
    }
    if date_jo:
        date_limite = date_jo + timedelta(days=DELAI_PRUDENT_JOURS)
        jours_restants = (date_limite - aujourd_hui).days
        resultat.update(
            date_limite=date_limite,
            jours_restants=jours_restants,
            depasse=jours_restants < 0,
        )
    return resultat


def _format(d):
    return d.strftime("%d/%m/%Y") if d else "?"


def simplifier(texte):
    """« Saint-Aunès » devient « saint aunes » : sans accents, ponctuation ni majuscules, pour comparer."""
    sans_accents = unicodedata.normalize("NFD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sans_accents.lower()).strip()


if __name__ == "__main__":
    communes_test = [
        ("Gif-sur-Yvette", "91190"),
        ("Arques", "62510"),
        ("Saint-Martin-Vésubie", "06450"),
    ]
    publication_la_plus_recente = None

    for nom, code_postal in communes_test:
        code_insee, nom_officiel = trouver_code_insee(nom, code_postal)
        arretes = [calculer_delai_declaration(a) for a in recuperer_arretes_catnat(code_insee)]
        # Les plus récents d'abord (l'API ne les trie pas)
        arretes.sort(key=lambda a: (a["publication_jo"] or date.min, a["debut_evenement"] or date.min), reverse=True)

        print(f"\n=== {nom_officiel} (INSEE {code_insee}) : {len(arretes)} arrêtés au total ===")
        for a in arretes[:3]:
            if a["depasse"]:
                statut = f"DÉPASSÉ depuis {-a['jours_restants']} jours"
            elif a["jours_restants"] is not None:
                statut = f"{a['jours_restants']} jours restants"
            else:
                statut = "pas encore publié au JO"
            print(f"- {a['type']}")
            print(f"    Événement : du {_format(a['debut_evenement'])} au {_format(a['fin_evenement'])}")
            print(f"    Publication JO : {_format(a['publication_jo'])}  ->  date limite : {_format(a['date_limite'])}  ({statut})")

        if arretes and arretes[0]["publication_jo"]:
            if not publication_la_plus_recente or arretes[0]["publication_jo"] > publication_la_plus_recente:
                publication_la_plus_recente = arretes[0]["publication_jo"]

    print(f"\nPublication au JO la plus récente trouvée : {_format(publication_la_plus_recente)}")

"""Inventaire des dommages visibles sur les photos du sinistré, par Nemotron VL.

L'IA décrit uniquement ce qui se voit : aucun prix, aucune valeur, aucune marque. Le code vérifie
chaque ligne (champs obligatoires, certitude, numéro de photo) et laisse la valeur estimée au
sinistré : « [À COMPLÉTER] ».
"""

import json
import re
from pathlib import Path

from llm import appeler_nemotron

MODELE_VISION = "nvidia/Nemotron-3.5-Super-VL"
A_COMPLETER = "[À COMPLÉTER]"
CHAMPS = ["zone", "objet", "dommage", "certitude", "photo"]
CERTAIN = "certain"
PROBABLE = "probable, à confirmer"
# Mots qui trahissent un prix ou une valeur : interdits dans l'inventaire
MOTS_INTERDITS = re.compile(r"€|\$|\beuros?\b|\bdollars?\b|\bprix\b|\bvaleur\b|\bco[uû]t\b", re.IGNORECASE)

CONSIGNES = f"""Tu es un expert en sinistres habitation. Tu regardes une photo de dégâts après une inondation
et tu listes en français les dommages VISIBLES sur cette photo.

Règles absolues :
- Uniquement ce qui se voit réellement sur la photo. Ne devine pas ce qui est hors champ ou caché.
- Uniquement les dommages causés par l'eau : eau stagnante, boue, dépôts, taches d'humidité,
  moisissure, objets renversés ou détrempés. L'usure ancienne (peinture écaillée, rouille, saleté
  habituelle) n'est PAS un dommage de l'inondation : ne la liste pas. En cas de doute, "{PROBABLE}".
- « zone » est le nom de la pièce, en un ou deux mots : cave, salon, cuisine, chambre, garage, entrée...
- Aucun prix, aucune valeur, aucun chiffre d'argent.
- Aucune marque ni modèle : décris l'objet de façon générique (« bouteille », « canapé en cuir »).
- « certitude » vaut "{CERTAIN}" si le dommage est clairement visible, sinon "{PROBABLE}".
- Un objet par ligne ; regroupe les objets identiques (« deux fauteuils »).
- Réponds uniquement avec un objet JSON, sans texte autour, de cette forme :
{{"dommages": [{{"zone": "pièce ou zone", "objet": "...", "dommage": "...", "certitude": "{CERTAIN}", "photo": 1}}]}}"""


def _extraire_json(texte):
    """Récupère l'objet JSON dans la réponse de l'IA (elle ajoute parfois du texte autour)."""
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut == -1 or fin == -1:
        raise ValueError("aucun JSON dans la réponse")
    return json.loads(texte[debut:fin + 1])


def verifier_ligne(ligne, numero_photo, nombre_photos):
    """Renvoie (ligne nettoyée, None) si la ligne est valable, sinon (None, raison du rejet)."""
    if not isinstance(ligne, dict):
        return None, "ce n'est pas un objet JSON"
    manquants = [c for c in CHAMPS if c not in ligne or str(ligne[c]).strip() == ""]
    if manquants:
        return None, f"champs manquants : {', '.join(manquants)}"
    try:
        photo = int(ligne["photo"])
    except (TypeError, ValueError):
        return None, f"numéro de photo invalide : {ligne['photo']!r}"
    if not 1 <= photo <= nombre_photos:
        return None, f"la photo n°{photo} n'existe pas"
    if photo != numero_photo:
        return None, f"la ligne parle de la photo n°{photo} alors que l'IA analysait la photo n°{numero_photo}"
    certitude = str(ligne["certitude"]).strip().lower()
    if certitude.startswith("certain"):
        certitude = CERTAIN
    elif certitude.startswith("probable"):
        certitude = PROBABLE
    else:
        return None, f"certitude inconnue : {ligne['certitude']!r}"
    textes = {c: str(ligne[c]).strip() for c in ("zone", "objet", "dommage")}
    if any(MOTS_INTERDITS.search(t) for t in textes.values()):
        return None, "mentionne un prix ou une valeur"
    return {**textes, "certitude": certitude, "photo": photo, "valeur_estimee": A_COMPLETER}, None


def analyser_photos(chemins):
    """Analyse chaque photo et renvoie l'inventaire des dommages visibles.

    `chemins` : chemins de fichiers, ou fichiers déjà ouverts en mémoire (photos envoyées depuis
    l'interface, jamais écrites sur le disque).
    Renvoie un dictionnaire : inventaire (lignes vérifiées), rejetees (lignes refusées et pourquoi),
    photos (noms des fichiers, dans l'ordre des numéros), tokens.
    """
    inventaire, rejetees = [], []
    tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for numero, chemin in enumerate(chemins, start=1):
        messages = [
            {"role": "system", "content": CONSIGNES},
            {"role": "user", "content": f"Voici la photo n°{numero}. Liste les dommages visibles."},
        ]
        for essai in range(2):
            texte, tokens_appel = appeler_nemotron(
                messages, modele=MODELE_VISION, images=[chemin], temperature=0, max_tokens=6000
            )
            for cle in tokens:
                tokens[cle] += tokens_appel[cle]
            try:
                lignes = _extraire_json(texte).get("dommages", [])
                break
            except ValueError:  # json.JSONDecodeError est aussi une ValueError
                if essai == 1:
                    rejetees.append({"photo": numero, "ligne": texte[:200], "raison": "réponse illisible (pas de JSON)"})
                    lignes = []
                    break
                messages += [{"role": "assistant", "content": texte},
                             {"role": "user", "content": "Réponds uniquement avec l'objet JSON demandé."}]

        for ligne in lignes:
            propre, raison = verifier_ligne(ligne, numero, len(chemins))
            if propre:
                inventaire.append(propre)
            else:
                rejetees.append({"photo": numero, "ligne": ligne, "raison": raison})

    # Un fichier envoyé depuis l'interface a un attribut .name ; un simple chemin texte non
    noms = [getattr(c, "name", None) or Path(c).name for c in chemins]
    return {"inventaire": inventaire, "rejetees": rejetees, "photos": [Path(n).name for n in noms], "tokens": tokens}


def inventaire_en_tableau(inventaire):
    """Tableau texte de l'inventaire (pour l'affichage et l'annexe de la lettre)."""
    entetes = ["N°", "Photo", "Zone", "Objet", "Dommage constaté", "Certitude", "Valeur estimée"]
    # Une ligne ajoutée à la main par le sinistré n'a pas de numéro de photo : « – »
    lignes = [[str(i), str(l["photo"] or "–"), l["zone"], l["objet"], l["dommage"], l["certitude"], l["valeur_estimee"]]
              for i, l in enumerate(inventaire, start=1)]
    largeurs = [max(len(x) for x in colonne) for colonne in zip(entetes, *lignes)]

    def formater(cellules):
        return "| " + " | ".join(c.ljust(n) for c, n in zip(cellules, largeurs)) + " |"

    separateur = "|" + "|".join("-" * (n + 2) for n in largeurs) + "|"
    return "\n".join([formater(entetes), separateur] + [formater(l) for l in lignes])


if __name__ == "__main__":
    from catnat import recuperer_arretes_catnat, trouver_code_insee
    from lettre import generer_lettre

    dossier = Path(__file__).parent / "exemples"
    chemins = sorted(dossier.glob("photo*.jpg"))
    analyse = analyser_photos(chemins)

    print("Photos analysées :")
    for numero, nom in enumerate(analyse["photos"], start=1):
        print(f"  {numero}. {nom}")
    print("\nINVENTAIRE DES DOMMAGES VISIBLES\n")
    print(inventaire_en_tableau(analyse["inventaire"]))
    for r in analyse["rejetees"]:
        print(f"\nLigne rejetée (photo {r['photo']}) : {r['raison']} -> {r['ligne']}")
    print(f"\nTokens (analyse des photos) : {analyse['tokens']['total_tokens']}")

    code_insee, _ = trouver_code_insee("Gif-sur-Yvette", "91190")
    arrete = next(
        a for a in recuperer_arretes_catnat(code_insee)
        if a["date_publication_jo"] == "04/11/2024" and "Inondation" in a["libelle_risque_jo"]
    )
    # Sinistré FICTIF, pour le test uniquement
    sinistre = {
        "nom": "Camille Exemple",
        "adresse": "1 rue Fictive, 91190 Gif-sur-Yvette",
        "assureur": "Assurance Fictive",
        "numero_contrat": "TEST-0000",
    }
    resultat = generer_lettre(arrete, sinistre, inventaire=analyse["inventaire"])

    print("\n" + "=" * 100)
    print(resultat["lettre"])
    print("=" * 100)
    for numero, raison in enumerate(resultat["rejets"], start=1):
        print(f"\nBrouillon n°{numero} refusé par la vérification : {raison}")
    t_photos, t_lettre = analyse["tokens"]["total_tokens"], resultat["tokens"]["total_tokens"]
    print(f"\nTokens : {t_photos} (photos) + {t_lettre} (lettre, {resultat['essais']} essai(s)) "
          f"= {t_photos + t_lettre} au total")

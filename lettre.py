"""Lettre de déclaration de sinistre catastrophe naturelle, rédigée par Nemotron.

Règle d'or : l'IA ne recopie jamais un fait (commune, dates, noms...). Elle écrit des étiquettes
comme {{DATE_JO}} et c'est le code qui les remplace par les vraies valeurs. Le brouillon de l'IA
est vérifié avant remplacement : s'il contient une date ou un chiffre inventé, il est refusé.
L'en-tête et la fin de la lettre sont entièrement écrits par le code ; l'IA ne rédige que le corps.
"""

import re
from datetime import date

from catnat import _format, calculer_delai_declaration, simplifier
from llm import appeler_nemotron

MODELE_LETTRE = "nvidia/nemotron-3-super-120b-a12b"
A_COMPLETER = "[À COMPLÉTER]"
NOMBRE_ESSAIS = 3
NOMBRE_PARAGRAPHES = 3

# Étiquettes que l'IA doit obligatoirement utiliser dans le corps, puis celles qu'elle peut utiliser
ETIQUETTES_OBLIGATOIRES = ["ADRESSE", "TYPE_CATASTROPHE", "DATE_DEBUT", "DATE_FIN", "COMMUNE"]
ETIQUETTES_FACULTATIVES = ["DATE_JO", "REFERENCE_ARRETE", "DATE_LIMITE", "ARTICLE_LOI", "NUMERO_CONTRAT", "ASSUREUR"]

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

# Textes que le corps doit contenir mot pour mot, et ceux que le code écrit déjà lui-même
TEXTES_OBLIGATOIRES = ["par {{TYPE_CATASTROPHE}}", "expert"]
TEXTES_INTERDITS = ["Objet :", "Madame, Monsieur", "Veuillez agréer", "Pièce jointe", "sinistré"]

# Premiers mots des types Géorisques qui sont féminins, ou singuliers bien que finissant par « s »
MOTS_FEMININS = {"sécheresse", "tempête", "crue", "submersion", "grêle", "lave", "coulée", "inondation"}
MOTS_SINGULIERS_EN_S = {"poids", "glissement"}

CONSIGNES = f"""Tu rédiges en français le corps d'une lettre de déclaration de sinistre catastrophe
naturelle, envoyée par un particulier à son assureur. L'en-tête, l'objet, « Madame, Monsieur, »,
la formule de politesse, la pièce jointe et la signature sont ajoutés par ailleurs : ne les écris pas.

Règles absolues :
- La lettre est écrite à la première personne, au nom du sinistré (« je »). N'écris jamais « le sinistré ».
- N'écris JAMAIS toi-même une adresse, une commune, une date, une référence ou un numéro.
  Utilise à la place ces étiquettes, écrites exactement ainsi, le code les remplira :
  {", ".join("{{" + e + "}}" for e in ETIQUETTES_OBLIGATOIRES)} (toutes obligatoires)
  {", ".join("{{" + e + "}}" for e in ETIQUETTES_FACULTATIVES)} (facultatives ; {{{{ARTICLE_LOI}}}} = l'article du Code des assurances)
- Aucun chiffre, aucun nom de mois. N'invente aucun montant, aucune date, aucun fait.
- N'affirme jamais que la déclaration est faite dans les délais ou hors délai.
- N'affirme pas ce que le sinistré possède ou a fait (photos, devis, factures, expertise...).
- {{{{TYPE_CATASTROPHE}}}} contient déjà son article (exemple : « les inondations ») : écris
  toujours « causé par {{{{TYPE_CATASTROPHE}}}} », sans rien ajouter devant.

Écris exactement {NOMBRE_PARAGRAPHES} paragraphes, séparés par une ligne vide :
1. Une phrase complète qui déclare le sinistre subi à {{{{ADRESSE}}}}, causé par {{{{TYPE_CATASTROPHE}}}}
   du {{{{DATE_DEBUT}}}} au {{{{DATE_FIN}}}} à {{{{COMMUNE}}}}, événement reconnu état de catastrophe
   naturelle par l'arrêté cité en objet.
2. Des phrases rédigées (avec un verbe, par exemple « Ces intempéries ont entraîné... ») qui décrivent
   les dégâts. Reprends chacun des dégâts fournis, sans en ajouter, sans en retirer, sans les
   aggraver, et sans inventer de lien de cause entre eux. Ne recopie pas la liste telle quelle.
   Si des dommages constatés sur photos sont fournis, le détail est déjà en annexe : résume-les en
   une phrase par pièce, puis renvoie à l'annexe. Pour ceux marqués « probable, à confirmer »,
   emploie une formulation prudente (« semble », « paraît »).
3. « Je » tiens les justificatifs à disposition (sans les énumérer), demande la prise en charge
   au titre de la garantie catastrophes naturelles et demande le passage d'un expert pour constater
   les dommages.
Réponds uniquement avec ces paragraphes, en texte brut, sans commentaire avant ou après."""


def _valeur(texte):
    """Une information vide devient [À COMPLÉTER]."""
    return texte.strip() if texte and texte.strip() else A_COMPLETER


def type_avec_article(libelle):
    """« Inondations et/ou Coulées de Boue » devient « les inondations et/ou coulées de boue »."""
    if not libelle:
        return A_COMPLETER
    texte = libelle.strip().lower()
    premier_mot = re.split(r"[\s-]", texte)[0]
    if premier_mot.endswith(("s", "x")) and premier_mot not in MOTS_SINGULIERS_EN_S:
        return "les " + texte
    if premier_mot[0] in "aàâeéèêiîoôuûyh":
        return "l'" + texte
    return ("la " if premier_mot in MOTS_FEMININS else "le ") + texte


def _paragraphes(texte):
    """Découpe le texte de l'IA en paragraphes (une ligne non vide = un paragraphe)."""
    return [ligne.strip() for ligne in texte.splitlines() if ligne.strip()]


def verifier_brouillon(brouillon, description_degats):
    """Renvoie la liste des problèmes du brouillon de l'IA (liste vide = brouillon accepté)."""
    problemes = []
    # L'IA écrit parfois l'apostrophe typographique ’ : on la ramène à ' avant de comparer
    brouillon_normalise = brouillon.replace("’", "'")
    for texte in TEXTES_OBLIGATOIRES:
        if texte not in brouillon_normalise:
            problemes.append(f"texte obligatoire absent : « {texte} »")
    for texte in TEXTES_INTERDITS:
        if texte in brouillon_normalise:
            problemes.append(f"« {texte} » est déjà écrit par le code, ne l'écris pas")
    paragraphes = _paragraphes(brouillon)
    if len(paragraphes) != NOMBRE_PARAGRAPHES:
        problemes.append(f"{len(paragraphes)} paragraphes au lieu de {NOMBRE_PARAGRAPHES}")
    elif description_degats and simplifier(paragraphes[1]) == simplifier(description_degats):
        problemes.append("le paragraphe des dégâts recopie la description au lieu de la rédiger")
    trouvees = set(re.findall(r"\{\{([A-Z_]+)\}\}", brouillon))
    inconnues = trouvees - set(ETIQUETTES_OBLIGATOIRES) - set(ETIQUETTES_FACULTATIVES)
    if inconnues:
        problemes.append(f"étiquettes inconnues : {', '.join(sorted(inconnues))}")
    manquantes = set(ETIQUETTES_OBLIGATOIRES) - trouvees
    if manquantes:
        problemes.append(f"étiquettes obligatoires manquantes : {', '.join(sorted(manquantes))}")
    # Seuls les chiffres déjà présents dans la description du sinistré sont autorisés
    chiffres_inventes = set(re.findall(r"\d+", brouillon)) - set(re.findall(r"\d+", description_degats))
    if chiffres_inventes:
        problemes.append(f"chiffres écrits par l'IA : {', '.join(sorted(chiffres_inventes))}")
    mois_inventes = [m for m in MOIS
                     if re.search(rf"\b{m}\b", brouillon, re.IGNORECASE)
                     and not re.search(rf"\b{m}\b", description_degats, re.IGNORECASE)]
    if mois_inventes:
        problemes.append(f"noms de mois écrits par l'IA : {', '.join(mois_inventes)}")
    return problemes


def checklist_pieces(arrete_calcule, reference_arrete):
    """Liste des pièces à joindre ou à préparer (fixe, écrite par le code et non par l'IA)."""
    return [
        "Preuve de dépôt du recommandé et copie de cette lettre (à conserver)",
        f"Copie de l'arrêté CatNat {reference_arrete}, publié au JO le "
        f"{_format(arrete_calcule['publication_jo'])} (à joindre, disponible sur legifrance.gouv.fr)",
        "Photos et vidéos des dégâts (si possible avant tout nettoyage)",
        "Liste détaillée des biens endommagés, avec leur valeur estimée",
        "Factures d'achat, garanties ou tout justificatif de la valeur des biens",
        "Devis ou factures de réparation et de remplacement",
        "Attestation d'un professionnel pour les équipements hors service",
        "Conserver les biens endommagés jusqu'au passage de l'expert",
        "Copie du contrat d'assurance habitation (conditions particulières)",
        "RIB pour le versement de l'indemnisation",
    ]


def generer_lettre(arrete, sinistre, inventaire=None):
    """Rédige la lettre de déclaration pour un arrêté CatNat (tel que renvoyé par catnat.py).

    `sinistre` est un dictionnaire avec les clés : nom, adresse, assureur, numero_contrat,
    description_degats. Toute information absente devient [À COMPLÉTER].
    `inventaire` (facultatif) : lignes renvoyées par photos.analyser_photos(). Elles servent à décrire
    les dégâts et sont ajoutées en annexe de la lettre.
    Renvoie un dictionnaire : lettre, checklist, delai_depasse, jours_restants, tokens, essais, rejets.
    """
    # Import ici pour que lettre.py fonctionne aussi sans photos
    from photos import inventaire_en_description, inventaire_en_tableau

    calcul = calculer_delai_declaration(arrete)
    description = sinistre.get("description_degats") or ""
    if inventaire:
        description = (description + "\n" if description else "") + (
            "Dommages constatés sur photos (l'inventaire détaillé est joint en annexe, "
            "tu peux le mentionner) :\n" + inventaire_en_description(inventaire)
        )
    reference = _valeur(arrete.get("code_national_catnat"))

    # Les faits viennent uniquement de l'arrêté et des infos du sinistré, jamais de l'IA
    valeurs = {
        "NOM": _valeur(sinistre.get("nom")),
        "ADRESSE": _valeur(sinistre.get("adresse")),
        "ASSUREUR": _valeur(sinistre.get("assureur")),
        "ADRESSE_ASSUREUR": _valeur(sinistre.get("adresse_assureur")),
        "NUMERO_CONTRAT": _valeur(sinistre.get("numero_contrat")),
        "COMMUNE": _valeur(arrete.get("libelle_commune")),
        "TYPE_CATASTROPHE": type_avec_article(calcul["type"]),
        "DATE_DEBUT": _valeur(calcul["debut_evenement"] and _format(calcul["debut_evenement"])),
        "DATE_FIN": _valeur(calcul["fin_evenement"] and _format(calcul["fin_evenement"])),
        "DATE_JO": _valeur(calcul["publication_jo"] and _format(calcul["publication_jo"])),
        "DATE_LIMITE": _valeur(calcul["date_limite"] and _format(calcul["date_limite"])),
        "REFERENCE_ARRETE": reference,
        "ARTICLE_LOI": "L125-2 du Code des assurances",
        "DATE_DU_JOUR": _format(date.today()),
    }

    messages = [
        {"role": "system", "content": CONSIGNES},
        {"role": "user", "content": f"Dégâts à décrire :\n{_valeur(description)}"},
    ]
    tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    rejets = []  # raisons pour lesquelles un brouillon a été refusé

    for essai in range(1, NOMBRE_ESSAIS + 1):
        brouillon, tokens_appel = appeler_nemotron(
            messages, modele=MODELE_LETTRE, temperature=0.3, max_tokens=6000
        )
        for cle in tokens:
            tokens[cle] += tokens_appel[cle]
        problemes = verifier_brouillon(brouillon, description)
        if not problemes:
            break
        rejets.append(" ; ".join(problemes))
        # On renvoie ses erreurs à l'IA pour qu'elle corrige
        messages += [
            {"role": "assistant", "content": brouillon},
            {"role": "user", "content": "Ton texte ne respecte pas les règles : " + " ; ".join(problemes)
                                        + ". Réécris les paragraphes en corrigeant ces points."},
        ]
    else:
        raise ValueError(f"Lettre refusée après {NOMBRE_ESSAIS} essais : {' ; '.join(problemes)}")

    # En-tête et fin de lettre : écrits par le code, avec une ligne vide entre chaque bloc
    v = valeurs
    blocs = [
        f"{v['NOM']}\n{v['ADRESSE']}",
        f"{v['ASSUREUR']}\n{v['ADRESSE_ASSUREUR']}",
        "Lettre recommandée avec accusé de réception",
        f"{v['COMMUNE']}, le {v['DATE_DU_JOUR']}",
        f"Objet : Déclaration de sinistre catastrophe naturelle – arrêté {v['REFERENCE_ARRETE']} "
        f"publié au Journal officiel du {v['DATE_JO']} – contrat {v['NUMERO_CONTRAT']}",
        "Madame, Monsieur,",
        *_paragraphes(brouillon),
        "Veuillez agréer, Madame, Monsieur, l'expression de mes salutations distinguées.",
        "Pièces jointes : copie de l'arrêté ; inventaire des dommages constatés sur photos (en annexe)"
        if inventaire else "Pièce jointe : copie de l'arrêté",
        v["NOM"],
    ]
    if inventaire:
        blocs += [
            "-" * 40,
            "Annexe : inventaire des dommages constatés sur photos",
            inventaire_en_tableau(inventaire),
            "Inventaire établi automatiquement à partir des photos : à relire et corriger par le sinistré "
            "avant envoi. « probable, à confirmer » : dommage qui semble visible mais doit être vérifié "
            "par l'expert. La valeur estimée de chaque bien est à compléter par le sinistré.",
        ]
    lettre = "\n\n".join(blocs)
    for etiquette, valeur in valeurs.items():
        lettre = lettre.replace("{{" + etiquette + "}}", valeur)

    checklist = checklist_pieces(calcul, reference)
    if inventaire:
        checklist += [
            "Photos originales des dégâts, numérotées comme dans l'inventaire en annexe",
            "Colonne « valeur estimée » de l'inventaire à compléter, ligne par ligne",
        ]

    return {
        "lettre": lettre,
        "checklist": checklist,
        "delai_depasse": calcul["depasse"],
        "jours_restants": calcul["jours_restants"],
        "tokens": tokens,
        "essais": essai,
        "rejets": rejets,
    }


if __name__ == "__main__":
    from catnat import recuperer_arretes_catnat, trouver_code_insee

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
        "description_degats": "Cave inondée, chaudière et machine à laver hors service.",
    }

    resultat = generer_lettre(arrete, sinistre)

    print("=" * 70)
    print(resultat["lettre"])
    print("=" * 70)
    print("\nPièces à joindre / à préparer :")
    for piece in resultat["checklist"]:
        print(f"  [ ] {piece}")
    for numero, raison in enumerate(resultat["rejets"], start=1):
        print(f"\nBrouillon n°{numero} refusé par la vérification : {raison}")
    if resultat["delai_depasse"]:
        print(f"\nATTENTION : délai de déclaration dépassé depuis {-resultat['jours_restants']} jours.")
    t = resultat["tokens"]
    print(f"\nTokens consommés : {t['prompt_tokens']} (consignes) + {t['completion_tokens']} (lettre)"
          f" = {t['total_tokens']} au total, en {resultat['essais']} essai(s)")

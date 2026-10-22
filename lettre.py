"""Lettre de déclaration de sinistre catastrophe naturelle, rédigée par Nemotron.

Règle d'or : l'IA ne recopie jamais un fait (commune, dates, noms...). Elle écrit des étiquettes
comme {{DATE_JO}} et c'est le code qui les remplace par les vraies valeurs. Le brouillon de l'IA
est vérifié avant remplacement : s'il contient une date ou un chiffre inventé, il est refusé.
L'en-tête et la fin de la lettre sont entièrement écrits par le code ; l'IA ne rédige que le corps.

Deux modes :
- avec arrêté (cas A ou E du radar) : les faits viennent de l'arrêté Géorisques ;
- sans arrêté (cas B, C ou D) : le sinistré déclare dès maintenant ; le type et les dates de
  l'événement sont ceux qu'il a saisis, et la lettre n'affirme jamais que l'événement est reconnu.
"""

import re
from datetime import date

from catnat import _format, calculer_delai_declaration, simplifier
from llm import appeler_nemotron

MODELE_LETTRE = "nvidia/nemotron-3-super-120b-a12b"
A_COMPLETER = "[À COMPLÉTER]"
NOMBRE_ESSAIS = 3
NOMBRE_PARAGRAPHES = 3
MAX_PHRASES_DEGATS = 3

# Annexe (écrite par le code) : partagée avec pdf.py et app.py
SEPARATEUR_ANNEXE = "-" * 40
TITRE_ANNEXE = "Annexe : inventaire des dommages constatés sur photos"
NOTE_ANNEXE = (
    "Inventaire établi automatiquement à partir des photos : à relire et corriger par le sinistré "
    "avant envoi. « probable, à confirmer » : dommage qui semble visible mais doit être vérifié "
    "par l'expert. La valeur estimée de chaque bien est à compléter par le sinistré."
)

# Étiquettes que l'IA doit obligatoirement utiliser dans le corps, puis celles qu'elle peut utiliser
ETIQUETTES_OBLIGATOIRES = ["ADRESSE", "TYPE_CATASTROPHE", "DATE_DEBUT", "DATE_FIN", "COMMUNE"]
ETIQUETTES_FACULTATIVES_SANS_ARRETE = ["ARTICLE_LOI", "NUMERO_CONTRAT", "ASSUREUR"]
ETIQUETTES_FACULTATIVES = ["DATE_JO", "REFERENCE_ARRETE", "DATE_LIMITE"] + ETIQUETTES_FACULTATIVES_SANS_ARRETE

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

# Textes que le corps doit contenir mot pour mot, et ceux que le code écrit déjà lui-même
TEXTES_OBLIGATOIRES = ["par {{TYPE_CATASTROPHE}}", "expert"]
# « énumérer » : l'IA a déjà recopié une consigne (« sans les énumérer ») dans la lettre
TEXTES_INTERDITS = ["Objet :", "Madame, Monsieur", "Veuillez agréer", "Pièce jointe", "sinistré", "énumérer"]
# Sans arrêté, la lettre ne doit jamais laisser croire que l'événement est déjà reconnu
TEXTES_INTERDITS_SANS_ARRETE = ["reconnu", "arrêté cité en objet"]

# Premiers mots des types Géorisques qui sont féminins, ou singuliers bien que finissant par « s »
MOTS_FEMININS = {"sécheresse", "tempête", "crue", "submersion", "grêle", "lave", "coulée", "inondation"}
MOTS_SINGULIERS_EN_S = {"poids", "glissement"}


def _obligatoires(une_seule_date):
    """Avec un événement d'un seul jour, {{DATE_FIN}} n'est pas utilisée (« le 20/10/2026 »)."""
    return [e for e in ETIQUETTES_OBLIGATOIRES if not (une_seule_date and e == "DATE_FIN")]


def _consignes(avec_arrete, une_seule_date=False):
    """Consignes données à l'IA ; seul le premier paragraphe change selon qu'il y a un arrêté ou non."""
    facultatives = ETIQUETTES_FACULTATIVES if avec_arrete else ETIQUETTES_FACULTATIVES_SANS_ARRETE
    periode = "le {{DATE_DEBUT}}" if une_seule_date else "du {{DATE_DEBUT}} au {{DATE_FIN}}"
    if avec_arrete:
        paragraphe_1 = (
            "Une phrase complète qui déclare le sinistre subi à {{ADRESSE}}, causé par {{TYPE_CATASTROPHE}}\n"
            f"   {periode} à {{{{COMMUNE}}}}, événement reconnu état de catastrophe\n"
            "   naturelle par l'arrêté cité en objet."
        )
    else:
        paragraphe_1 = (
            "Une phrase complète qui déclare le sinistre subi à {{ADRESSE}}, causé par {{TYPE_CATASTROPHE}}\n"
            f"   {periode} à {{{{COMMUNE}}}}, et qui précise que tu le déclares dès\n"
            "   maintenant, sans attendre la publication d'un éventuel arrêté de catastrophe naturelle.\n"
            "   N'écris jamais que l'événement est reconnu : aucun arrêté n'est encore publié."
        )
    return f"""Tu rédiges en français le corps d'une lettre de déclaration de sinistre catastrophe
naturelle, envoyée par un particulier à son assureur. L'en-tête, l'objet, « Madame, Monsieur, »,
la formule de politesse, les pièces jointes et la signature sont ajoutés par ailleurs : ne les écris pas.

Règles absolues :
- La lettre est écrite à la première personne, au nom du sinistré (« je »). N'écris jamais « le sinistré ».
- N'écris JAMAIS toi-même une adresse, une commune, une date, une référence ou un numéro.
  Utilise à la place ces étiquettes, écrites exactement ainsi, le code les remplira :
  {", ".join("{{" + e + "}}" for e in _obligatoires(une_seule_date))} (toutes obligatoires)
  {", ".join("{{" + e + "}}" for e in facultatives)} (facultatives ; {{{{ARTICLE_LOI}}}} = l'article du Code des assurances)
- Aucun chiffre, aucun nom de mois. N'invente aucun montant, aucune date, aucun fait.
- N'affirme jamais que la déclaration est faite dans les délais ou hors délai.
- N'affirme pas ce que le sinistré possède ou a fait (photos, devis, factures, expertise...).
- {{{{TYPE_CATASTROPHE}}}} contient déjà son article (exemple : « les inondations ») : écris
  toujours « causé par {{{{TYPE_CATASTROPHE}}}} », sans rien ajouter devant.

Écris exactement {NOMBRE_PARAGRAPHES} paragraphes, séparés par une ligne vide :
1. {paragraphe_1}
2. Au maximum {MAX_PHRASES_DEGATS} phrases courtes, avec un verbe, qui RÉSUMENT les dégâts pièce par pièce
   (par exemple « Dans le salon, ... »). Reprends les dégâts fournis sans en ajouter, sans les
   aggraver et sans inventer de lien de cause entre eux. Ne recopie pas la liste telle quelle.
   Pour ceux marqués « probable, à confirmer », emploie une formulation prudente (« semble »).
   Si un inventaire est joint en annexe, termine par UN SEUL renvoi à l'annexe.
3. « Je » tiens les justificatifs à votre disposition (ne dresse pas leur liste), demande la prise en charge
   au titre de la garantie catastrophes naturelles et demande le passage d'un expert pour constater
   les dommages.
Réponds uniquement avec ces paragraphes, en texte brut, sans commentaire avant ou après."""


def _valeur(texte):
    """Une information vide devient [À COMPLÉTER]."""
    return texte.strip() if texte and texte.strip() else A_COMPLETER


def _date(valeur):
    """Accepte une date Python ou un texte « jj/mm/aaaa » ; vide -> [À COMPLÉTER]."""
    if isinstance(valeur, date):
        return _format(valeur)
    return _valeur(valeur)


def type_avec_article(libelle):
    """« Inondations et/ou Coulées de Boue » devient « les inondations et/ou coulées de boue »."""
    if not libelle or not libelle.strip():
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


def verifier_brouillon(brouillon, description_degats, avec_arrete=True, avec_inventaire=False, une_seule_date=False):
    """Renvoie la liste des problèmes du brouillon de l'IA (liste vide = brouillon accepté)."""
    problemes = []
    # L'IA écrit parfois l'apostrophe typographique ’ : on la ramène à ' avant de comparer
    brouillon_normalise = brouillon.replace("’", "'")
    for texte in TEXTES_OBLIGATOIRES:
        if texte not in brouillon_normalise:
            problemes.append(f"texte obligatoire absent : « {texte} »")
    interdits = TEXTES_INTERDITS + ([] if avec_arrete else TEXTES_INTERDITS_SANS_ARRETE)
    for texte in interdits:
        if texte in brouillon_normalise:
            problemes.append(f"« {texte} » ne doit pas apparaître dans le corps de la lettre")
    paragraphes = _paragraphes(brouillon)
    if len(paragraphes) != NOMBRE_PARAGRAPHES:
        problemes.append(f"{len(paragraphes)} paragraphes au lieu de {NOMBRE_PARAGRAPHES}")
    else:
        degats = paragraphes[1]
        if description_degats and simplifier(degats) == simplifier(description_degats):
            problemes.append("le paragraphe des dégâts recopie la description au lieu de la rédiger")
        nombre_phrases = len(re.findall(r"[.!?](?:\s|$)", degats))
        if nombre_phrases > MAX_PHRASES_DEGATS:
            problemes.append(f"le paragraphe des dégâts fait {nombre_phrases} phrases (maximum {MAX_PHRASES_DEGATS})")
    if avec_inventaire and brouillon_normalise.lower().count("annexe") != 1:
        problemes.append("il faut exactement un renvoi à l'annexe")
    obligatoires = _obligatoires(une_seule_date)
    autorisees = set(ETIQUETTES_OBLIGATOIRES) | set(
        ETIQUETTES_FACULTATIVES if avec_arrete else ETIQUETTES_FACULTATIVES_SANS_ARRETE)
    trouvees = set(re.findall(r"\{\{([A-Z_]+)\}\}", brouillon))
    inconnues = trouvees - autorisees
    if inconnues:
        problemes.append(f"étiquettes non autorisées : {', '.join(sorted(inconnues))}")
    manquantes = set(obligatoires) - trouvees
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
    if arrete_calcule:
        piece_arrete = (f"Copie de l'arrêté CatNat {reference_arrete}, publié au JO le "
                        f"{_format(arrete_calcule['publication_jo'])} (à joindre, disponible sur legifrance.gouv.fr)")
    else:
        piece_arrete = ("Surveiller la publication de l'arrêté CatNat au Journal officiel (legifrance.gouv.fr) : "
                        "la déclaration doit parvenir à l'assureur au plus tard 30 jours après cette publication")
    return [
        "Preuve de dépôt du recommandé et copie de cette lettre (à conserver)",
        piece_arrete,
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
    """Rédige la lettre de déclaration de sinistre.

    `arrete` : arrêté CatNat tel que renvoyé par catnat.py, ou None s'il n'y en a pas encore.
    `sinistre` : dictionnaire avec les clés nom, adresse, assureur, adresse_assureur, numero_contrat,
    description_degats ; et, sans arrêté : commune, type_evenement, date_debut, date_fin.
    Toute information absente devient [À COMPLÉTER].
    `inventaire` (facultatif) : lignes renvoyées par photos.analyser_photos() (éventuellement
    corrigées par le sinistré). Elles servent à décrire les dégâts et sont ajoutées en annexe.
    Renvoie un dictionnaire : lettre, checklist, delai_depasse, jours_restants, tokens, essais, rejets.
    """
    # Import ici pour que lettre.py fonctionne aussi sans photos
    from photos import inventaire_en_description, inventaire_en_tableau

    avec_arrete = arrete is not None
    calcul = calculer_delai_declaration(arrete) if avec_arrete else None
    description = sinistre.get("description_degats") or ""
    if inventaire:
        description = (description + "\n" if description else "") + (
            "Dommages constatés sur photos (l'inventaire détaillé est joint en annexe) :\n"
            + inventaire_en_description(inventaire)
        )
    reference = _valeur(arrete.get("code_national_catnat")) if avec_arrete else A_COMPLETER

    # Les faits viennent uniquement de l'arrêté et des infos du sinistré, jamais de l'IA
    valeurs = {
        "NOM": _valeur(sinistre.get("nom")),
        "ADRESSE": _valeur(sinistre.get("adresse")),
        "ASSUREUR": _valeur(sinistre.get("assureur")),
        "ADRESSE_ASSUREUR": _valeur(sinistre.get("adresse_assureur")),
        "NUMERO_CONTRAT": _valeur(sinistre.get("numero_contrat")),
        "ARTICLE_LOI": "L125-2 du Code des assurances",
        "DATE_DU_JOUR": _format(date.today()),
        "REFERENCE_ARRETE": reference,
    }
    if avec_arrete:
        valeurs.update({
            "COMMUNE": _valeur(arrete.get("libelle_commune")),
            "TYPE_CATASTROPHE": type_avec_article(calcul["type"]),
            "DATE_DEBUT": _date(calcul["debut_evenement"]),
            "DATE_FIN": _date(calcul["fin_evenement"]),
            "DATE_JO": _date(calcul["publication_jo"]),
            "DATE_LIMITE": _date(calcul["date_limite"]),
        })
    else:
        date_debut = sinistre.get("date_debut")
        valeurs.update({
            "COMMUNE": _valeur(sinistre.get("commune")),
            "TYPE_CATASTROPHE": type_avec_article(sinistre.get("type_evenement")),
            "DATE_DEBUT": _date(date_debut),
            "DATE_FIN": _date(sinistre.get("date_fin") or date_debut),
        })

    une_seule_date = valeurs["DATE_DEBUT"] == valeurs["DATE_FIN"]
    messages = [
        {"role": "system", "content": _consignes(avec_arrete, une_seule_date)},
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
        problemes = verifier_brouillon(brouillon, description, avec_arrete, bool(inventaire), une_seule_date)
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
    if avec_arrete:
        objet = (f"Objet : Déclaration de sinistre catastrophe naturelle – arrêté {v['REFERENCE_ARRETE']} "
                 f"publié au Journal officiel du {v['DATE_JO']} – contrat {v['NUMERO_CONTRAT']}")
    else:
        periode = v["DATE_DEBUT"] if une_seule_date else f"{v['DATE_DEBUT']} au {v['DATE_FIN']}"
        objet = (f"Objet : Déclaration de sinistre – événement du {periode} à {v['COMMUNE']} "
                 f"– contrat {v['NUMERO_CONTRAT']}")
    pieces = (["copie de l'arrêté"] if avec_arrete else []) + (
        ["inventaire des dommages constatés sur photos (en annexe)"] if inventaire else [])
    blocs = [
        f"{v['NOM']}\n{v['ADRESSE']}",
        f"{v['ASSUREUR']}\n{v['ADRESSE_ASSUREUR']}",
        "Lettre recommandée avec accusé de réception",
        f"{v['COMMUNE']}, le {v['DATE_DU_JOUR']}",
        objet,
        "Madame, Monsieur,",
        *_paragraphes(brouillon),
        "Veuillez agréer, Madame, Monsieur, l'expression de mes salutations distinguées.",
    ]
    if pieces:
        blocs.append(("Pièces jointes : " if len(pieces) > 1 else "Pièce jointe : ") + " ; ".join(pieces))
    blocs.append(v["NOM"])
    if inventaire:
        blocs += [SEPARATEUR_ANNEXE, TITRE_ANNEXE, inventaire_en_tableau(inventaire), NOTE_ANNEXE]
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
        "delai_depasse": calcul["depasse"] if calcul else None,
        "jours_restants": calcul["jours_restants"] if calcul else None,
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

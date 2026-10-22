"""Lettre de déclaration de sinistre catastrophe naturelle, rédigée par Nemotron.

Règle d'or : l'IA ne recopie jamais un fait (commune, dates, noms...). Elle écrit des étiquettes
comme {{DATE_JO}} et c'est le code qui les remplace par les vraies valeurs. Le brouillon de l'IA
est vérifié avant remplacement : s'il contient une date ou un chiffre inventé, il est refusé.
L'en-tête et la fin de la lettre sont entièrement écrits par le code ; l'IA ne rédige que le corps.

Deux modes :
- avec arrêté (cas A ou E du radar) : les faits viennent de l'arrêté Géorisques ;
- sans arrêté (cas B, C ou D) : le sinistré déclare dès maintenant ; le type et les dates de
  l'événement sont ceux qu'il a saisis, et la lettre n'affirme jamais que l'événement est reconnu.

L'IA répond en JSON avec exactement 3 champs (un par paragraphe) : le code assemble la lettre.
Si l'IA échoue 3 fois (ou ne répond pas), le code écrit une lettre de secours à partir d'un
modèle fixe : l'utilisateur obtient toujours une lettre, jamais une erreur.
"""

import json
import re
from datetime import date

from catnat import _format, calculer_delai_declaration, simplifier
from llm import appeler_nemotron

MODELE_LETTRE = "nvidia/nemotron-3-super-120b-a12b"
A_COMPLETER = "[À COMPLÉTER]"
NOMBRE_ESSAIS = 4
MAX_MOTS_DEGATS = 60  # le détail objet par objet est dans l'annexe
# Les 2 premiers essais se font sans la « réflexion » du modèle : réponse 10 fois moins chère, et le
# code vérifie de toute façon chaque brouillon. Si le paragraphe des dégâts reste trop long, les essais
# suivants se font avec réflexion (le modèle peut alors compter ses mots), avec une limite large pour
# que la réponse ne soit pas coupée.
ESSAIS_SANS_REFLEXION = 2
SANS_REFLEXION = {"chat_template_kwargs": {"enable_thinking": False}}
# Les 3 champs du JSON renvoyé par l'IA, dans l'ordre de la lettre
CHAMPS_LETTRE = ["paragraphe_declaration", "paragraphe_degats", "paragraphe_demande"]

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

# Textes que chaque paragraphe doit contenir mot pour mot, et ceux que le code écrit déjà lui-même
TEXTES_OBLIGATOIRES = {"paragraphe_declaration": ["par {{TYPE_CATASTROPHE}}"], "paragraphe_demande": ["expert"]}
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


def _periode(une_seule_date):
    """« le {{DATE_DEBUT}} » pour un événement d'un seul jour, sinon « du ... au ... »."""
    return "le {{DATE_DEBUT}}" if une_seule_date else "du {{DATE_DEBUT}} au {{DATE_FIN}}"


def _consignes(avec_arrete, une_seule_date=False):
    """Consignes données à l'IA ; seul le premier paragraphe change selon qu'il y a un arrêté ou non."""
    facultatives = ETIQUETTES_FACULTATIVES if avec_arrete else ETIQUETTES_FACULTATIVES_SANS_ARRETE
    periode = _periode(une_seule_date)
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

Réponds uniquement avec un objet JSON, sans texte avant ou après, qui contient exactement ces
3 champs. Chaque champ est UN SEUL paragraphe, sans retour à la ligne :
{{"paragraphe_declaration": "...", "paragraphe_degats": "...", "paragraphe_demande": "..."}}

- paragraphe_declaration : {paragraphe_1}
- paragraphe_degats : {MAX_MOTS_DEGATS} mots AU MAXIMUM, en deux ou trois phrases courtes. Un court résumé
   par pièce, qui cite DEUX éléments AU PLUS, les plus importants (par exemple « Dans le salon, le sol
   et les canapés sont couverts de boue. »). Ne cite pas tous les objets : ils sont dans l'annexe. Reprends les dégâts fournis sans
   en ajouter, sans les aggraver et sans inventer de lien de cause entre eux. Pour ceux marqués
   « probable, à confirmer », emploie une formulation prudente (« semble »). Si un inventaire est
   joint en annexe, termine par UN SEUL renvoi à l'annexe, qui contient le détail.
   Longueur attendue, sur l'exemple d'un AUTRE logement (ne le recopie pas) : « Dans le garage, le sol
   et les cartons sont couverts de boue. Dans la chambre, le lit et la moquette sont détrempés, et le mur
   semble taché. L'inventaire détaillé est joint en annexe. »
- paragraphe_demande : « je » tiens les justificatifs à votre disposition (ne dresse pas leur liste),
   demande la prise en charge au titre de la garantie catastrophes naturelles et demande le passage
   d'un expert pour constater les dommages."""


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


def _un_seul_paragraphe(texte):
    """Fusionne un texte écrit sur plusieurs lignes en un seul paragraphe (au lieu de le refuser)."""
    return " ".join(ligne.strip() for ligne in texte.splitlines() if ligne.strip())


def lire_reponse(reponse):
    """Lit le JSON de l'IA. Renvoie (les 3 paragraphes dans l'ordre, None) ou (None, problème)."""
    debut, fin = reponse.find("{"), reponse.rfind("}")
    try:
        # strict=False : accepte un vrai retour à la ligne à l'intérieur d'un champ
        donnees = json.loads(reponse[debut:fin + 1], strict=False) if debut != -1 else None
    except ValueError:
        # Lecture de secours : un guillemet " non échappé dans un paragraphe casse le JSON ;
        # on récupère alors chaque champ entre son nom et le nom du champ suivant.
        motif = r'\s*,\s*'.join(rf'"{c}"\s*:\s*"(.*?)"' for c in CHAMPS_LETTRE) + r'\s*}'
        trouve = re.search(motif, reponse, re.DOTALL)
        donnees = dict(zip(CHAMPS_LETTRE, trouve.groups())) if trouve else None
    if not isinstance(donnees, dict):
        return None, "la réponse n'est pas un objet JSON valide"
    manquants = [c for c in CHAMPS_LETTRE if not isinstance(donnees.get(c), str) or not donnees[c].strip()]
    if manquants:
        return None, f"champs JSON manquants ou vides : {', '.join(manquants)}"
    # Un éventuel champ en plus est ignoré : seuls les 3 champs demandés entrent dans la lettre
    paragraphes = [_un_seul_paragraphe(donnees[c]) for c in CHAMPS_LETTRE]
    return [p[0].upper() + p[1:] for p in paragraphes], None  # « je tiens... » -> « Je tiens... »


def compter_mots(texte):
    """Nombre de vrais mots : « l'eau » compte pour un mot, la ponctuation seule (« : », « ; », « – ») pour zéro."""
    return len(re.findall(r"\w+(?:['’-]\w+)*", texte))


def pieces_inventaire(inventaire):
    """Les pièces de l'inventaire, dans l'ordre où elles apparaissent (sans les cases vides)."""
    return list(dict.fromkeys(l["zone"] for l in inventaire or [] if l["zone"] and l["zone"] != A_COMPLETER))


def resume_par_piece(inventaire):
    """Les dégâts regroupés par pièce, pour que l'IA résume pièce par pièce au lieu de tout recopier."""
    lignes = []
    for piece in pieces_inventaire(inventaire) + ([A_COMPLETER] if any(l["zone"] == A_COMPLETER for l in inventaire) else []):
        objets = [f"{l['objet']} ({l['dommage']}" + ("" if l["certitude"] == "certain" else ", probable, à confirmer") + ")"
                  for l in inventaire if l["zone"] == piece]
        lignes.append(f"- {piece} : " + " ; ".join(objets))
    return "\n".join(lignes)


def _consigne_longueur(inventaire):
    """Budget de mots par pièce, rappelé dans la demande (le modèle le respecte mieux qu'une règle générale)."""
    nombre = len(pieces_inventaire(inventaire))
    if not nombre:
        return f"Paragraphe des dégâts : {MAX_MOTS_DEGATS} mots au maximum.\n\n"
    return (f"Paragraphe des dégâts : {nombre} pièce(s) à citer, {MAX_MOTS_DEGATS} mots au maximum en tout, "
            f"soit {max(5, (MAX_MOTS_DEGATS - 12) // nombre - 3)} mots AU PLUS par pièce. Une seule courte phrase par pièce, "
            f"qui cite DEUX éléments AU PLUS (les plus importants) : ne cite pas tous les objets.\n\n")


def verifier_brouillon(paragraphes, description_degats, avec_arrete=True, avec_inventaire=False, une_seule_date=False,
                       pieces=()):
    """Renvoie la liste des problèmes des 3 paragraphes de l'IA (liste vide = brouillon accepté).

    `pieces` : pièces de l'inventaire, qui doivent toutes être citées dans le paragraphe des dégâts.
    """
    problemes = []
    # L'IA écrit parfois l'apostrophe typographique ’ : on la ramène à ' avant de comparer
    champs = {c: p.replace("’", "'") for c, p in zip(CHAMPS_LETTRE, paragraphes)}
    brouillon = "\n\n".join(champs.values())
    for champ, textes in TEXTES_OBLIGATOIRES.items():
        for texte in textes:
            if texte not in champs[champ]:
                problemes.append(f"texte obligatoire absent de {champ} : « {texte} »")
    interdits = TEXTES_INTERDITS + ([] if avec_arrete else TEXTES_INTERDITS_SANS_ARRETE)
    for champ, paragraphe in champs.items():
        for texte in interdits:
            if texte in paragraphe:
                problemes.append(f"« {texte} » ne doit pas apparaître dans {champ}")
    degats = champs["paragraphe_degats"]
    if description_degats and simplifier(degats) == simplifier(description_degats):
        problemes.append("le paragraphe des dégâts recopie la description au lieu de la rédiger")
    nombre_mots = compter_mots(degats)
    if nombre_mots > MAX_MOTS_DEGATS:
        # Consigne concrète, phrase par phrase : le modèle sait mieux raccourcir une phrase précise
        phrases = [p.strip() for p in re.split(r"(?<=[.!?])\s+", degats) if p.strip()]
        cible = max(5, (MAX_MOTS_DEGATS - 4) // max(1, len(phrases) - 1) - 2)
        longues = [f"« {p} » ({compter_mots(p)} mots, vise {cible})" for p in phrases if compter_mots(p) > cible]
        problemes.append(f"le paragraphe des dégâts fait {nombre_mots} mots (maximum {MAX_MOTS_DEGATS}) : "
                         f"raccourcis ces phrases en gardant une vraie phrase avec un verbe : {' ; '.join(longues)}. "
                         f"Termine simplement par « Détail en annexe. »")
    oubliees = [p for p in pieces if simplifier(p) not in simplifier(degats)]
    if oubliees:
        problemes.append(f"pièces absentes du paragraphe des dégâts : {', '.join(oubliees)}")
    if avec_inventaire and (brouillon.lower().count("annexe") != 1 or "annexe" not in degats.lower()):
        problemes.append("il faut exactement un renvoi à l'annexe, dans paragraphe_degats")
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


def paragraphes_de_secours(avec_arrete, une_seule_date, description_sinistre, inventaire):
    """Les 3 paragraphes écrits entièrement par le code (modèle fixe), si l'IA échoue.

    Mêmes étiquettes que pour l'IA : le code les remplace ensuite par les vraies valeurs.
    Les dégâts : les pièces de l'inventaire relu par le sinistré (le détail est dans l'annexe) ;
    sans inventaire, la description écrite par le sinistré lui-même.
    """
    declaration = f"Je déclare le sinistre subi à {{{{ADRESSE}}}}, causé par {{{{TYPE_CATASTROPHE}}}} " \
                  f"{_periode(une_seule_date)} à {{{{COMMUNE}}}}"
    if avec_arrete:
        declaration += ", événement reconnu état de catastrophe naturelle par l'arrêté cité en objet."
    else:
        declaration += ". Je le déclare dès maintenant, sans attendre la publication d'un éventuel " \
                       "arrêté de catastrophe naturelle."

    phrases = []
    description = "" if inventaire else _un_seul_paragraphe(description_sinistre or "")
    if description:
        if description[1:2].islower():  # « Eau et boue... » -> « eau et boue... » après les deux-points
            description = description[0].lower() + description[1:]
        phrases.append("J'ai constaté les dégâts suivants : " + description.rstrip(" .") + ".")
    if inventaire:
        pieces = list(dict.fromkeys(l["zone"] for l in inventaire if l["zone"] != A_COMPLETER))
        if pieces:
            phrases.append(f"Les pièces touchées sont : {', '.join(pieces)}.")
        phrases.append("Le détail des dommages figure dans l'inventaire joint en annexe.")
    if not phrases:
        phrases.append(f"J'ai constaté les dégâts suivants : {A_COMPLETER}.")

    demande = ("Je tiens les justificatifs à votre disposition. Je demande la prise en charge de ces dommages "
               "au titre de la garantie catastrophes naturelles, ainsi que le passage d'un expert pour les constater.")
    return [declaration, " ".join(phrases), demande]


def checklist_pieces(arrete_calcule, avec_inventaire=False, langue="fr"):
    """Pièces et démarches, en 3 blocs courts (écrits par le code, jamais par l'IA).

    Renvoie {"enveloppe": [...], "garder": [...], "faire": [...]} : à mettre dans l'enveloppe,
    à garder chez soi, à faire. `langue` : "fr" ou "en" (pour l'interface en anglais).
    """
    en = langue == "en"
    enveloppe = ["Your letter, dated and signed" if en else "Votre lettre, datée et signée"]
    if avec_inventaire:
        enveloppe.append("Page 2: the list of your damage (add the value of each item if you know it)" if en else
                         "La page 2 : la liste de vos dégâts (ajoutez la valeur des objets si vous la connaissez)")
    if arrete_calcule:
        jo = _format(arrete_calcule["publication_jo"])
        enveloppe.append(f"A copy of the natural disaster decree of {jo} (print it from legifrance.gouv.fr)" if en else
                         f"Une copie de l'arrêté de catastrophe naturelle du {jo} (à imprimer sur legifrance.gouv.fr)")
    enveloppe += [
        "Copies of a few photos of the damage" if en else "Des copies de quelques photos des dégâts",
        "Your bank details (RIB), to be paid" if en else "Votre relevé d'identité bancaire (RIB), pour être remboursé",
    ]
    garder = [
        "The original photos and videos of the damage" if en else "Les photos et vidéos originales des dégâts",
        "Invoices, quotes and warranties for your belongings" if en else "Les factures, devis et garanties de vos objets",
        "The damaged items, until the expert's visit" if en else "Les objets abîmés, jusqu'à la visite de l'expert",
        "The post office receipt for the registered letter, and a copy of your letter" if en else
        "Le reçu de La Poste pour le recommandé, et une copie de votre lettre",
    ]
    if arrete_calcule and not arrete_calcule["depasse"]:
        limite = _format(arrete_calcule["date_limite"])
        faire = [f"Send the letter by registered post with acknowledgement of receipt, before {limite}" if en else
                 f"Envoyer la lettre en recommandé avec accusé de réception, avant le {limite}"]
    elif arrete_calcule:
        faire = ["Send the letter by registered post with acknowledgement of receipt today, and call your insurer" if en
                 else "Envoyer la lettre en recommandé avec accusé de réception aujourd'hui, et appeler votre assurance"]
    else:
        faire = [
            "Send the letter by registered post with acknowledgement of receipt, right now" if en else
            "Envoyer la lettre en recommandé avec accusé de réception, dès maintenant",
            "Watch for the decree in the Journal officiel (legifrance.gouv.fr): your claim must reach your insurer "
            "30 days after it at the latest" if en else
            "Surveiller la publication de l'arrêté au Journal officiel (legifrance.gouv.fr) : votre déclaration "
            "doit arriver chez l'assurance au plus tard 30 jours après",
        ]
    return {"enveloppe": enveloppe, "garder": garder, "faire": faire}


def generer_lettre(arrete, sinistre, inventaire=None):
    """Rédige la lettre de déclaration de sinistre.

    `arrete` : arrêté CatNat tel que renvoyé par catnat.py, ou None s'il n'y en a pas encore.
    `sinistre` : dictionnaire avec les clés nom, adresse, assureur, adresse_assureur, numero_contrat,
    description_degats ; et, sans arrêté : commune, type_evenement, date_debut, date_fin.
    Toute information absente devient [À COMPLÉTER].
    `inventaire` (facultatif) : lignes renvoyées par photos.analyser_photos() (éventuellement
    corrigées par le sinistré). Elles servent à décrire les dégâts et sont ajoutées en annexe.
    Renvoie un dictionnaire : lettre, checklist, delai_depasse, jours_restants, tokens, essais, rejets,
    secours (True si la lettre vient du modèle fixe du code, parce que l'IA a échoué).
    Ne lève jamais d'erreur à cause de l'IA : dans le pire des cas, c'est la lettre de secours.
    """
    # Import ici pour que lettre.py fonctionne aussi sans photos
    from photos import inventaire_en_tableau

    avec_arrete = arrete is not None
    calcul = calculer_delai_declaration(arrete) if avec_arrete else None
    description = sinistre.get("description_degats") or ""
    if inventaire:
        description = (description + "\n" if description else "") + (
            "Dommages constatés sur photos, regroupés par pièce (l'inventaire détaillé est joint en annexe) :\n"
            + resume_par_piece(inventaire)
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
        {"role": "user", "content": _consigne_longueur(inventaire) + f"Dégâts à résumer :\n{_valeur(description)}"},
    ]
    tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    rejets = []  # raisons pour lesquelles un brouillon a été refusé
    paragraphes, essais = None, 0

    for essais in range(1, NOMBRE_ESSAIS + 1):
        try:
            options = ({"max_tokens": 2000, "extra_body": SANS_REFLEXION} if essais <= ESSAIS_SANS_REFLEXION
                       else {"max_tokens": 12000})
            reponse, tokens_appel = appeler_nemotron(messages, modele=MODELE_LETTRE, temperature=0.3, **options)
        except Exception as erreur:  # IA indisponible, budget de tokens épuisé... : lettre de secours
            rejets.append(f"appel à l'IA impossible : {erreur}")
            break
        for cle in tokens:
            tokens[cle] += tokens_appel[cle]
        paragraphes, probleme = lire_reponse(reponse)
        problemes = [probleme] if probleme else verifier_brouillon(
            paragraphes, description, avec_arrete, bool(inventaire), une_seule_date, pieces_inventaire(inventaire))
        if not problemes:
            break
        paragraphes = None
        rejets.append(" ; ".join(problemes))
        # On renvoie ses erreurs à l'IA pour qu'elle corrige
        messages += [
            {"role": "assistant", "content": reponse},
            {"role": "user", "content": "Ta réponse ne respecte pas les règles : " + " ; ".join(problemes)
                                        + ". Renvoie l'objet JSON corrigé, avec les 3 champs."},
        ]

    secours = paragraphes is None
    if secours:
        paragraphes = paragraphes_de_secours(avec_arrete, une_seule_date, sinistre.get("description_degats"),
                                             inventaire)

    # En-tête et fin de lettre : écrits par le code, avec une ligne vide entre chaque bloc
    v = valeurs
    if avec_arrete:
        objet = (f"Objet : Déclaration de sinistre catastrophe naturelle – arrêté {v['REFERENCE_ARRETE']} "
                 f"publié au Journal officiel du {v['DATE_JO']} – contrat {v['NUMERO_CONTRAT']}")
    else:
        periode = v["DATE_DEBUT"] if une_seule_date else f"{v['DATE_DEBUT']} au {v['DATE_FIN']}"  # après « du »
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
        *paragraphes,
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

    checklist = checklist_pieces(calcul, bool(inventaire))

    return {
        "lettre": lettre,
        "checklist": checklist,
        "delai_depasse": calcul["depasse"] if calcul else None,
        "jours_restants": calcul["jours_restants"] if calcul else None,
        "tokens": tokens,
        "essais": essais,
        "rejets": rejets,
        "secours": secours,
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
    for bloc, pieces in resultat["checklist"].items():
        print(f"\n{bloc} :")
        for piece in pieces:
            print(f"  [ ] {piece}")
    for numero, raison in enumerate(resultat["rejets"], start=1):
        print(f"\nBrouillon n°{numero} refusé par la vérification : {raison}")
    if resultat["secours"]:
        print("\nVersion simplifiée : l'IA a échoué, la lettre vient du modèle fixe du code.")
    if resultat["delai_depasse"]:
        print(f"\nATTENTION : délai de déclaration dépassé depuis {-resultat['jours_restants']} jours.")
    t = resultat["tokens"]
    print(f"\nTokens consommés : {t['prompt_tokens']} (consignes) + {t['completion_tokens']} (lettre)"
          f" = {t['total_tokens']} au total, en {resultat['essais']} essai(s)")

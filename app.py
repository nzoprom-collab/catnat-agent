"""30 Days : interface web (Streamlit) pour les sinistrés d'une catastrophe naturelle en France.

Lancer :  .venv/bin/streamlit run app.py

Public visé : une personne âgée, stressée, peu à l'aise avec l'informatique, souvent sur téléphone.
D'où : gros textes, une seule action principale par écran, aucun jargon, aucune info technique
visible (elles sont rangées dans le panneau « Comment ça marche ? » en bas de page).

Confidentialité : rien de personnel n'est écrit sur le disque. Les photos et les informations du
sinistré restent en mémoire, dans la session du navigateur, et disparaissent à la fermeture de la page.
Seuls des résultats publics (arrêtés Géorisques, recherches web, photos de démo) sont mis en cache.
"""

import base64
import html
import io
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
import streamlit as st
from PIL import Image, ImageOps

from catnat import GEO_API, _format, calculer_delai_declaration, recuperer_arretes_catnat
from lettre import A_COMPLETER, MODELE_LETTRE, SEPARATEUR_ANNEXE, checklist_pieces, generer_lettre
from llm import LimiteTokensAtteinte
from pdf import lettre_en_pdf
from photos import CERTAIN, MODELE_VISION, PROBABLE, analyser_photos
from radar import (AUTRE_SITE, MODELE_RADAR, NON_OFFICIEL, OFFICIEL_LOCAL, PRESSE, RESEAU_SOCIAL,
                   analyser_situation, rechercher_actualites)

DOSSIER = Path(__file__).parent
PHOTOS_DEMO = sorted((DOSSIER / "exemples").glob("photo*.jpg"))
URL_DEPOT = "https://github.com/nzoprom-collab/catnat-agent"
LIMITES = {"analyses": 3, "lettres": 2, "photos": 6}  # par visite, pour protéger la démo publique
TAILLE_MINIATURE = 240  # pixels : assez pour reconnaître la photo, léger sur téléphone

# Données FICTIVES pré-remplies par le bouton « Voir un exemple »
DEMO = {
    "saisie_commune": "Martigues",
    "saisie_dep": "13",
    "description": "Eau et boue dans la cave, le salon et la cuisine.",
    "f_nom": "Camille Exemple (démo)",
    "f_adresse": "1 rue Fictive, 13500 Martigues",
    "f_assureur": "Assurance Fictive",
    "f_adresse_assureur": "",
    "f_contrat": "DEMO-0000",
    "f_type": "Inondations et coulées de boue",
    "f_debut": date(2026, 10, 20),
    "f_fin": None,
}
# Champs saisis par l'utilisateur, conservés quand il change d'étape (voir garder_saisies)
SAISIES = {"saisie_commune": "", "saisie_dep": "", "description": "", "f_nom": "", "f_adresse": "",
           "f_assureur": "", "f_adresse_assureur": "", "f_contrat": "", "f_type": None, "f_debut": None, "f_fin": None}
# Types d'événements proposés dans la liste (on peut aussi écrire le sien) : ils restent en français, comme la lettre
TYPES_EVENEMENT = ["Inondations et coulées de boue", "Inondations par remontées de nappe phréatique",
                   "Mouvements de terrain", "Sécheresse", "Tempête", "Grêle", "Submersion marine"]

# ---------------------------------------------------------------------------------------------
# Textes de l'interface (français / anglais). La lettre, elle, est toujours en français.
# ---------------------------------------------------------------------------------------------
TEXTES = {
    "fr": {
        "slogan": "Ne ratez plus jamais votre délai de déclaration",
        "demo": "✨ Voir un exemple (démo)",
        "demo_aide": "Remplit tout avec un exemple : une vraie commune (Martigues) et 3 photos. La personne est fictive.",
        "etapes": ["Votre commune", "Vos dégâts", "Votre lettre"],
        "etape_n": "Étape {n} sur 3 : {nom}",
        # Étape 1
        "intro_1": "Nous vérifions si l'état de catastrophe naturelle est reconnu dans votre commune, "
                   "et jusqu'à quand vous pouvez prévenir votre assurance.",
        "commune": "Nom de votre commune",
        "departement": "Département (facultatif)",
        "departement_aide": "Le numéro de votre département, par exemple 13. Utile si plusieurs communes portent le même nom.",
        "choisir_commune": "Choisissez votre commune dans la liste",
        "aucune_commune": "Nous ne trouvons pas cette commune. Vérifiez l'orthographe.",
        "erreur_geo": "La recherche de communes ne répond pas pour l'instant. Réessayez dans un instant.",
        "analyser": "Voir la situation de ma commune",
        "choisir_d_abord": "Tapez le nom de votre commune, puis choisissez-la dans la liste.",
        "analyse_en_cours": "Nous consultons les sites officiels et l'actualité… (environ 30 secondes)",
        "q_situation": "Que se passe-t-il dans ma commune ?",
        "q_faire": "Que dois-je faire ?",
        "q_date": "Avant quelle date ?",
        "statuts": {
            "A": "✅ Catastrophe naturelle reconnue",
            "B": "📰 Reconnaissance annoncée, pas encore confirmée",
            "C": "⏳ Demande de reconnaissance en cours",
            "E": "⚠️ Reconnue, mais le délai est dépassé",
            "D": "ℹ️ Aucune démarche en cours",
        },
        "situation": {
            "A": "L'État a reconnu l'état de catastrophe naturelle à {commune} ({type}). "
                 "La décision est parue au Journal officiel le {jo}.",
            "B": "Des articles récents annoncent que l'État a reconnu la catastrophe naturelle à {commune}. "
                 "Ce n'est pas encore confirmé par le site officiel Géorisques.",
            "C": "La mairie de {commune} a demandé à l'État de reconnaître l'état de catastrophe naturelle. "
                 "La décision n'est pas encore publiée.",
            "E": "L'État a reconnu l'état de catastrophe naturelle à {commune} ({type}). "
                 "La décision est parue au Journal officiel le {jo}, il y a plus de 30 jours.",
            "D": "Nous n'avons trouvé aucune démarche récente de reconnaissance de catastrophe naturelle à {commune}.",
        },
        "faire": {
            "A": "Prévenez votre assurance par lettre recommandée avec accusé de réception. Nous vous aidons à l'écrire.",
            "B": "Prévenez votre assurance dès maintenant par lettre recommandée, sans attendre la confirmation "
                 "officielle. Nous vous aidons à l'écrire.",
            "C": "N'attendez pas la décision : prévenez votre assurance dès maintenant par lettre recommandée, "
                 "et signalez vos dégâts à votre mairie. Nous vous aidons à écrire la lettre.",
            "E": "Appelez votre assurance tout de suite et expliquez votre situation. Envoyez quand même "
                 "votre lettre recommandée : nous vous aidons à l'écrire.",
            "D": "Si vous avez des dégâts, prévenez quand même votre assurance et votre mairie : "
                 "la mairie peut demander la reconnaissance à l'État.",
        },
        "date": {
            "A": "Avant le {limite}",
            "B": "Le plus vite possible",
            "C": "Dès maintenant",
            "E": "Aujourd'hui",
            "D": "Le plus vite possible",
        },
        "date_detail": {
            "A": "La loi vous donne 30 jours après la parution au Journal officiel. Nous gardons 1 jour de marge.",
            "B": "Le délai de 30 jours a peut-être déjà commencé : la date de parution se vérifie sur legifrance.gouv.fr.",
            "C": "Quand la décision paraîtra au Journal officiel, vous aurez 30 jours au maximum.",
            "E": "La date limite était le {limite}.",
            "D": "Si une reconnaissance paraît un jour au Journal officiel, vous aurez 30 jours après sa parution.",
        },
        "compte": "Il vous reste <b>{n}</b> jours",
        "compte_1": "C'est le <b>dernier jour</b>",
        "info_depasse": "Pour information : un autre arrêté de catastrophe naturelle (« {type} ») est paru au "
                        "Journal officiel le {jo}. Son délai s'est terminé le {limite}.",
        "pourquoi": "🔎 Pourquoi on vous dit ça ? (sources)",
        "resume_ia": "Résumé rédigé par l'IA, à partir des sources ci-dessous :",
        "sources_fr": "",
        "voir_source": "voir la source",
        "georisques": "Géorisques, site officiel de l'État",
        "badges": {"Géorisques": "Officiel", OFFICIEL_LOCAL: "Site public local", PRESSE: "Presse",
                   RESEAU_SOCIAL: "Réseau social", AUTRE_SITE: "Autre site"},
        "a_verifier": "À vérifier",
        "continuer_degats": "Continuer : mes dégâts →",
        "continuer_lettre": "Continuer : ma lettre →",
        "retour": "← Revenir à l'étape précédente",
        # Étape 2
        "intro_2": "Ajoutez des photos de vos dégâts. L'IA fait la liste de ce qu'elle voit, puis vous vérifiez chaque élément.",
        "prive": "🔒 Vos photos ne sont pas enregistrées : elles disparaissent quand vous fermez la page.",
        "photos_demo_info": "📸 Exemple : 3 photos d'inondation libres de droits.",
        "credits_photos": "Photos : B137 (CC0), King Prince (CC BY 2.0), Infrogmation (CC BY 2.5), Wikimedia Commons.",
        "utiliser_mes_photos": "Utiliser mes propres photos",
        "ajouter_photos": "Choisissez vos photos (6 au maximum)",
        "aide_photos": "Photos encore possibles pendant cette visite : {n}.",
        "description": "Décrivez vos dégâts avec vos mots (facultatif)",
        "description_exemple": "Par exemple : l'eau est montée de 50 cm dans le salon, la chaudière ne marche plus…",
        "analyser_photos": "Analyser mes photos ({n})",
        "sans_photos": "Je n'ai pas de photos",
        "analyse_photos_en_cours": "L'IA regarde vos photos une par une… (environ 20 secondes par photo)",
        "trop_de_photos": "6 photos au maximum. Retirez-en quelques-unes.",
        "verifier_titre": "Vérifiez la liste de vos dégâts",
        "verifier_aide": "Pour chaque dégât, appuyez sur « Correct », « Modifier » ou « Supprimer ».",
        "verifies": "Vérifiés : <b>{n} sur {total}</b>",
        "tout_verifie": "Tout est vérifié. Vous pouvez continuer.",
        "liste_vide": "Aucun dégât dans la liste pour l'instant. Ajoutez-en un, ou décrivez vos dégâts plus bas.",
        "onglet_liste": "📋 Liste",
        "onglet_tableau": "🧮 Vue tableau",
        "correct": "✅ Correct",
        "modifier": "✏️ Modifier",
        "supprimer": "🗑️ Supprimer",
        "verifie": "✓ Vérifié",
        "a_confirmer": "À confirmer par l'expert",
        "photo_n": "Photo {n}",
        "sans_photo": "Ajouté par vous",
        "valeur_txt": "Valeur : {v}",
        "supprime": "Dégât supprimé : « {objet} ».",
        "annuler_suppression": "↩️ Annuler la suppression",
        "ajouter": "➕ Ajouter un dégât oublié",
        "champ_zone": "Pièce (par exemple : salon)",
        "champ_objet": "Objet ou partie du logement",
        "champ_dommage": "Dégât constaté",
        "champ_valeur": "Valeur estimée en euros (facultatif)",
        "champ_valeur_aide": "Laissez vide si vous ne savez pas : la lettre indiquera [À COMPLÉTER].",
        "champ_incertain": "Je ne suis pas sûr : à confirmer par l'expert",
        "enregistrer": "Enregistrer",
        "annuler": "Annuler",
        "objet_obligatoire": "Indiquez au moins l'objet abîmé.",
        "tableau_aide": "Pour ceux qui préfèrent un tableau : modifiez les cases, ajoutez une ligne en bas, "
                        "ou cochez une ligne puis 🗑️ pour la supprimer. Cliquez ensuite sur « Enregistrer le tableau ».",
        "enregistrer_tableau": "Enregistrer le tableau (j'ai tout vérifié)",
        "colonnes": {"photo": "Photo", "zone": "Pièce", "objet": "Objet", "dommage": "Dégât constaté",
                     "certitude": "Certitude", "valeur": "Valeur (€)"},
        "rien_a_declarer": "Ajoutez des photos, un dégât ou une description pour continuer.",
        "reste_a_verifier": "Vérifiez chaque dégât de la liste pour continuer.",
        # Étape 3
        "intro_3": "Remplissez vos informations : nous préparons votre lettre à l'assurance, prête à imprimer.",
        "lettre_avec_arrete": "📄 Votre lettre citera la décision officielle (arrêté de catastrophe naturelle) "
                              "parue au Journal officiel le **{jo}**.",
        "lettre_sans_arrete": "📄 Aucune décision n'est encore publiée : votre lettre déclare vos dégâts **dès maintenant**. "
                              "Indiquez le type de catastrophe et sa date.",
        "lettre_en_francais": "",
        "alerte_depasse": "⚠️ Le délai est dépassé : appelez aussi votre assurance aujourd'hui.",
        "nom": "Vos nom et prénom",
        "adresse": "Adresse du logement abîmé",
        "assureur": "Nom de votre assurance",
        "adresse_assureur": "Adresse de votre assurance",
        "contrat": "Numéro de contrat",
        "aide_contrat": "Vous le trouverez sur votre contrat ou sur votre dernier avis d'échéance.",
        "type_evenement": "Type de catastrophe",
        "type_choisir": "Choisissez dans la liste ou écrivez",
        "date_debut": "Date de la catastrophe (premier jour)",
        "date_fin": "Dernier jour (si cela a duré plusieurs jours)",
        "vide_a_completer": "Si vous ne connaissez pas une information, laissez la case vide : "
                            "la lettre indiquera [À COMPLÉTER] et vous l'écrirez à la main.",
        "generer": "Préparer ma lettre",
        "generation": "Nous préparons votre lettre… (environ 30 secondes)",
        "lettre_prete": "✅ Votre lettre est prête.",
        "telecharger": "⬇️ Télécharger ma lettre (PDF)",
        "a_envoyer": "Imprimez-la, relisez-la, signez-la, puis envoyez-la **en recommandé avec accusé de réception** "
                     "(au guichet de La Poste).",
        "version_simplifiee": "Version simplifiée : cette lettre a été rédigée à partir d'un modèle fixe. Relisez-la bien.",
        "lire_lettre": "📄 Lire ma lettre avant de l'imprimer",
        "page_2": "Page 2 : la liste de vos {n} dégâts, avec une colonne « valeur » à compléter.",
        "modifier_infos": "✏️ Modifier mes informations",
        "blocs": {"enveloppe": "✉️ À mettre dans l'enveloppe", "garder": "🏠 À garder chez vous", "faire": "✅ À faire"},
        # Messages
        "limite_analyses": "Pour protéger ce service gratuit, chaque visite est limitée à 3 recherches de commune. "
                           "Revenez plus tard.",
        "limite_lettres": "Pour protéger ce service gratuit, chaque visite est limitée à 2 lettres. Revenez plus tard.",
        "limite_photos": "Pour protéger ce service gratuit, chaque visite est limitée à 6 photos. Il vous en reste {n}.",
        "limite_tokens": "Ce service gratuit a atteint sa limite d'utilisation. Merci de revenir plus tard.",
        "erreur_technique": "Le service ne répond pas pour l'instant. Réessayez dans quelques minutes.",
        # Bas de page
        "comment": "🧭 Comment ça marche ?",
        "comment_code": "#### 🧮 Fait par le code (fiable, vérifiable)",
        "comment_code_liste": [
            "**Faits officiels** : arrêtés de catastrophe naturelle (Géorisques), communes (geo.api.gouv.fr)",
            "**Dates limites** : parution au Journal officiel + 29 jours (la loi accorde 30 jours, article L125-2 du Code des assurances)",
            "**Vérification des sources web** : page réellement trouvée, citation présente mot pour mot, type de site, nom de la commune",
            "**Dernier mot sur la situation** de la commune, et **tous les conseils** affichés",
            "**Lettre** : en-tête, objet, dates et références écrits par le code ; un brouillon de l'IA est refusé s'il invente un chiffre ou une date, ou si le paragraphe des dégâts dépasse 60 mots",
            "**Garde-fous** : budget de tokens, limites par visite",
        ],
        "comment_ia": "#### 🤖 Fait par l'IA (NVIDIA Nemotron, via Nebius)",
        "comment_ia_liste": [
            "**Analyse de la situation** à partir des arrêtés et de l'actualité : `{radar}`",
            "**Lecture des photos** et liste des dégâts visibles : `{vision}`",
            "**Rédaction du corps de la lettre**, avec des étiquettes que le code remplit : `{lettre}`",
            "**Recherche web** : Tavily (2 recherches par commune, gardées 24 h en mémoire)",
        ],
        "comment_regle": "**Règle d'or** : l'IA n'invente jamais un fait. Elle rédige et classe ; le code fournit et vérifie les faits.",
        "technique": "#### 🔧 Détails techniques de votre visite",
        "tech_cas": "Situation retenue par le code : cas **{cas}** ({libelle})",
        "tech_tokens": "Tokens consommés : commune {radar} · photos {photos} · lettre {lettre}",
        "tech_corrections": "Corrections du code sur l'analyse de l'IA :",
        "tech_aucune_correction": "Aucune correction : l'analyse de l'IA est cohérente avec les données et les sources vérifiées.",
        "tech_rejetees": "Affirmations de l'IA rejetées par le code :",
        "tech_lignes_rejetees": "Lignes de l'inventaire photo rejetées par le code : {n}",
        "tech_brouillons": "Brouillons de lettre refusés par le code : {n} · lettre de secours : {secours}",
        "tech_erreurs": "Erreurs techniques :",
        "oui": "oui", "non": "non",
        "session": "Pendant cette visite : {a} recherche(s) sur 3 · {l} lettre(s) sur 2 · {p} photo(s) sur 6.",
        "effacer": "🧹 Effacer mes informations et recommencer",
        "confidentialite": "🔒 Rien n'est enregistré sur notre serveur : vos photos et informations restent le temps "
                           "de votre visite. Les photos sont envoyées à l'IA (Nebius) uniquement pour être analysées.",
        "avertissement": "⚖️ Outil d'aide : il ne remplace pas un conseil juridique. Vérifiez votre contrat et contactez votre assurance.",
        "pied": "Prototype réalisé pour le hackathon Nebius x NVIDIA · NVIDIA Nemotron · Tavily · données Géorisques et geo.api.gouv.fr",
        "code_source": "code source",
    },
    "en": {
        "slogan": "Never miss your disaster claim deadline",
        "demo": "✨ See an example (demo)",
        "demo_aide": "Fills everything with an example: a real town (Martigues) and 3 photos. The person is fictitious.",
        "etapes": ["Your town", "Your damage", "Your letter"],
        "etape_n": "Step {n} of 3: {nom}",
        "intro_1": "We check whether a natural disaster has been officially recognised in your town, "
                   "and until when you can notify your insurer.",
        "commune": "Name of your town (commune)",
        "departement": "Département (optional)",
        "departement_aide": "Your French département number, for example 13. Useful when several towns share a name.",
        "choisir_commune": "Choose your town from the list",
        "aucune_commune": "We cannot find this town. Please check the spelling.",
        "erreur_geo": "The town search is not responding right now. Please try again in a moment.",
        "analyser": "See the situation in my town",
        "choisir_d_abord": "Type the name of your town, then choose it from the list.",
        "analyse_en_cours": "We are checking official websites and the news… (about 30 seconds)",
        "q_situation": "What is happening in my town?",
        "q_faire": "What should I do?",
        "q_date": "By when?",
        "statuts": {
            "A": "✅ Natural disaster officially recognised",
            "B": "📰 Recognition announced, not yet confirmed",
            "C": "⏳ Recognition request in progress",
            "E": "⚠️ Recognised, but the deadline has passed",
            "D": "ℹ️ No procedure in progress",
        },
        "situation": {
            "A": "The French State has officially recognised a natural disaster in {commune} ({type}). "
                 "The decision was published in the Official Journal on {jo}.",
            "B": "Recent articles say the French State has recognised a natural disaster in {commune}. "
                 "This is not yet confirmed by the official Géorisques website.",
            "C": "The town hall of {commune} has asked the French State to recognise a natural disaster. "
                 "The decision has not been published yet.",
            "E": "The French State has officially recognised a natural disaster in {commune} ({type}). "
                 "The decision was published in the Official Journal on {jo}, more than 30 days ago.",
            "D": "We found no recent request for natural disaster recognition in {commune}.",
        },
        "faire": {
            "A": "Notify your insurer by registered letter with acknowledgement of receipt. We help you write it.",
            "B": "Notify your insurer right now by registered letter, without waiting for official confirmation. "
                 "We help you write it.",
            "C": "Don't wait for the decision: notify your insurer right now by registered letter, and report "
                 "your damage to your town hall. We help you write the letter.",
            "E": "Call your insurer right away and explain your situation. Send your registered letter anyway: "
                 "we help you write it.",
            "D": "If you have damage, notify your insurer and your town hall anyway: the town hall can ask "
                 "the State for recognition.",
        },
        "date": {"A": "Before {limite}", "B": "As soon as possible", "C": "Right now", "E": "Today",
                 "D": "As soon as possible"},
        "date_detail": {
            "A": "The law gives you 30 days after publication in the Official Journal. We keep 1 day of margin.",
            "B": "The 30-day period may have already started: the publication date can be checked on legifrance.gouv.fr.",
            "C": "When the decision is published in the Official Journal, you will have 30 days at most.",
            "E": "The deadline was {limite}.",
            "D": "If a recognition is ever published in the Official Journal, you will have 30 days after it.",
        },
        "compte": "<b>{n}</b> days left",
        "compte_1": "This is the <b>last day</b>",
        "info_depasse": "For your information: another natural disaster decree (“{type}”) was published in the "
                        "Official Journal on {jo}. Its deadline ended on {limite}.",
        "pourquoi": "🔎 Why are we telling you this? (sources)",
        "resume_ia": "Summary written by the AI, based on the sources below (in French):",
        "sources_fr": "The sources are French websites: their texts are shown in French.",
        "voir_source": "see the source",
        "georisques": "Géorisques, official French government website",
        "badges": {"Géorisques": "Official", OFFICIEL_LOCAL: "Local public website", PRESSE: "Press",
                   RESEAU_SOCIAL: "Social media", AUTRE_SITE: "Other website"},
        "a_verifier": "To be checked",
        "continuer_degats": "Next: my damage →",
        "continuer_lettre": "Next: my letter →",
        "retour": "← Back to the previous step",
        "intro_2": "Add photos of your damage. The AI lists what it sees, then you check each item.",
        "prive": "🔒 Your photos are not stored: they disappear when you close the page.",
        "photos_demo_info": "📸 Example: 3 royalty-free photos of floods.",
        "credits_photos": "Photos: B137 (CC0), King Prince (CC BY 2.0), Infrogmation (CC BY 2.5), Wikimedia Commons.",
        "utiliser_mes_photos": "Use my own photos",
        "ajouter_photos": "Choose your photos (6 maximum)",
        "aide_photos": "Photos still allowed during this visit: {n}.",
        "description": "Describe your damage in your own words (optional, French if possible)",
        "description_exemple": "For example: the water rose 50 cm in the living room, the boiler no longer works…",
        "analyser_photos": "Analyse my photos ({n})",
        "sans_photos": "I have no photos",
        "analyse_photos_en_cours": "The AI is looking at your photos one by one… (about 20 seconds per photo)",
        "trop_de_photos": "6 photos maximum. Please remove some.",
        "verifier_titre": "Check the list of your damage",
        "verifier_aide": "For each item, tap “Correct”, “Edit” or “Delete”. The list stays in French for your insurer.",
        "verifies": "Checked: <b>{n} of {total}</b>",
        "tout_verifie": "Everything is checked. You can continue.",
        "liste_vide": "No damage in the list yet. Add one, or describe your damage below.",
        "onglet_liste": "📋 List",
        "onglet_tableau": "🧮 Table view",
        "correct": "✅ Correct",
        "modifier": "✏️ Edit",
        "supprimer": "🗑️ Delete",
        "verifie": "✓ Checked",
        "a_confirmer": "To be confirmed by the expert",
        "photo_n": "Photo {n}",
        "sans_photo": "Added by you",
        "valeur_txt": "Value: {v}",
        "supprime": "Item deleted: “{objet}”.",
        "annuler_suppression": "↩️ Undo",
        "ajouter": "➕ Add a forgotten item",
        "champ_zone": "Room (for example: salon)",
        "champ_objet": "Item or part of the home",
        "champ_dommage": "Damage observed",
        "champ_valeur": "Estimated value in euros (optional)",
        "champ_valeur_aide": "Leave empty if you don't know: the letter will show [À COMPLÉTER] (to be completed).",
        "champ_incertain": "I'm not sure: to be confirmed by the expert",
        "enregistrer": "Save",
        "annuler": "Cancel",
        "objet_obligatoire": "Please enter at least the damaged item.",
        "tableau_aide": "For those who prefer a table: edit the cells, add a row at the bottom, or tick a row "
                        "then 🗑️ to delete it. Then click “Save the table”.",
        "enregistrer_tableau": "Save the table (I have checked everything)",
        "colonnes": {"photo": "Photo", "zone": "Room", "objet": "Item", "dommage": "Damage observed",
                     "certitude": "Certainty", "valeur": "Value (€)"},
        "rien_a_declarer": "Add photos, an item or a description to continue.",
        "reste_a_verifier": "Check each item of the list to continue.",
        "intro_3": "Fill in your details: we prepare your letter to your insurer, ready to print.",
        "lettre_avec_arrete": "📄 Your letter will cite the official decision (natural disaster decree) "
                              "published in the Official Journal on **{jo}**.",
        "lettre_sans_arrete": "📄 No decision has been published yet: your letter reports your damage **right now**. "
                              "Enter the type of disaster and its date.",
        "lettre_en_francais": "🇫🇷 Your letter is written **in French**: it goes to a French insurer, under French insurance law.",
        "alerte_depasse": "⚠️ The deadline has passed: also call your insurer today.",
        "nom": "Your full name",
        "adresse": "Address of the damaged home",
        "assureur": "Name of your insurer",
        "adresse_assureur": "Address of your insurer",
        "contrat": "Policy number",
        "aide_contrat": "You will find it on your policy or on your last premium notice.",
        "type_evenement": "Type of disaster (in French)",
        "type_choisir": "Choose from the list or type",
        "date_debut": "Date of the disaster (first day)",
        "date_fin": "Last day (if it lasted several days)",
        "vide_a_completer": "If you don't know something, leave it empty: the letter will show [À COMPLÉTER] "
                            "(to be completed) and you can write it by hand.",
        "generer": "Prepare my letter",
        "generation": "We are preparing your letter… (about 30 seconds)",
        "lettre_prete": "✅ Your letter is ready.",
        "telecharger": "⬇️ Download my letter (PDF)",
        "a_envoyer": "Print it, read it, sign it, then send it **by registered post with acknowledgement of receipt** "
                     "(at the post office counter).",
        "version_simplifiee": "Simplified version: this letter was written from a fixed template. Read it carefully.",
        "lire_lettre": "📄 Read my letter before printing it (in French)",
        "page_2": "Page 2: the list of your {n} damaged items, with a “value” column to complete.",
        "modifier_infos": "✏️ Change my details",
        "blocs": {"enveloppe": "✉️ To put in the envelope", "garder": "🏠 To keep at home", "faire": "✅ To do"},
        "limite_analyses": "To protect this free service, each visit is limited to 3 town searches. Please come back later.",
        "limite_lettres": "To protect this free service, each visit is limited to 2 letters. Please come back later.",
        "limite_photos": "To protect this free service, each visit is limited to 6 photos. You have {n} left.",
        "limite_tokens": "This free service has reached its usage limit. Please come back later.",
        "erreur_technique": "The service is not responding right now. Please try again in a few minutes.",
        "comment": "🧭 How it works",
        "comment_code": "#### 🧮 Done by the code (reliable, verifiable)",
        "comment_code_liste": [
            "**Official facts**: natural disaster decrees (Géorisques), towns (geo.api.gouv.fr)",
            "**Deadlines**: publication in the Official Journal + 29 days (the law allows 30 days, art. L125-2 of the French Insurance Code)",
            "**Web source checks**: page actually found, quote present word for word, type of website, town name",
            "**Final say on the town's situation**, and **every piece of advice** shown",
            "**Letter**: header, subject, dates and references written by the code; an AI draft is rejected if it invents a number or a date, or if the damage paragraph exceeds 60 words",
            "**Safeguards**: token budget, per-visit limits",
        ],
        "comment_ia": "#### 🤖 Done by the AI (NVIDIA Nemotron, via Nebius)",
        "comment_ia_liste": [
            "**Analysing the situation** from decrees and news: `{radar}`",
            "**Reading the photos** and listing visible damage: `{vision}`",
            "**Drafting the body of the letter**, with placeholders filled by the code: `{lettre}`",
            "**Web search**: Tavily (2 searches per town, kept 24 h in memory)",
        ],
        "comment_regle": "**Golden rule**: the AI never invents a fact. It drafts and classifies; the code provides and checks the facts.",
        "technique": "#### 🔧 Technical details of your visit",
        "tech_cas": "Situation retained by the code: case **{cas}** ({libelle})",
        "tech_tokens": "Tokens used: town {radar} · photos {photos} · letter {lettre}",
        "tech_corrections": "Corrections made by the code to the AI's analysis:",
        "tech_aucune_correction": "No correction: the AI's analysis is consistent with the data and the verified sources.",
        "tech_rejetees": "AI statements rejected by the code:",
        "tech_lignes_rejetees": "Photo inventory lines rejected by the code: {n}",
        "tech_brouillons": "Letter drafts rejected by the code: {n} · fallback letter: {secours}",
        "tech_erreurs": "Technical errors:",
        "oui": "yes", "non": "no",
        "session": "During this visit: {a} search(es) of 3 · {l} letter(s) of 2 · {p} photo(s) of 6.",
        "effacer": "🧹 Delete my details and start over",
        "confidentialite": "🔒 Nothing is stored on our server: your photos and details are kept only during your "
                           "visit. Photos are sent to the AI (Nebius) only to be analysed.",
        "avertissement": "⚖️ Assistance tool: it does not replace legal advice. Check your policy and contact your insurer.",
        "pied": "Prototype built for the Nebius x NVIDIA hackathon · NVIDIA Nemotron · Tavily · data from Géorisques and geo.api.gouv.fr",
        "code_source": "source code",
    },
}

# Couleurs des cartes (une par situation) et des badges de source : contraste suffisant sur fond clair
COULEURS_CAS = {"A": "#14713f", "B": "#1f5fa8", "C": "#a84e00", "E": "#b42318", "D": "#4a5563"}
COULEURS_BADGES = {"Géorisques": "#0b6e4f", OFFICIEL_LOCAL: "#1f5fa8", PRESSE: "#6941c6",
                   RESEAU_SOCIAL: "#a84e00", AUTRE_SITE: "#4a5563"}

CSS = """
<style>
.block-container {max-width: 780px; padding-top: 1.2rem; padding-bottom: 3rem;}
p, li, label, input, textarea, .stMarkdown {font-size: 1rem;}
.marque {display: flex; align-items: baseline; gap: .6rem; flex-wrap: wrap; margin: 0;}
.marque .nom {font-size: 1.5rem; font-weight: 800; color: #1f2933;}
.marque .slogan {font-size: 1rem; color: #3e4c59;}
h2.etape {font-size: 1.9rem; font-weight: 800; line-height: 1.2; color: #1f2933; margin: .6rem 0 .3rem; padding: 0;}
.intro {font-size: 1.05rem; color: #1f2933; margin-bottom: .6rem;}
[data-testid="stWidgetLabel"] p {font-size: 1.05rem !important; font-weight: 600; color: #1f2933;}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {color: #3e4c59 !important; font-size: .95rem !important;}
.stButton button, .stDownloadButton button, .stFormSubmitButton button {
  min-height: 3.1rem; font-size: 1.05rem !important; font-weight: 600; border-radius: 12px;}
.stButton button p, .stDownloadButton button p, .stFormSubmitButton button p {font-size: 1.05rem !important;}
[data-testid="stBaseButton-primary"] {min-height: 3.6rem; font-size: 1.2rem !important;}
[data-testid="stBaseButton-primary"] p {font-size: 1.2rem !important; font-weight: 700;}
[data-testid="stExpander"] summary p {font-size: 1.05rem !important; font-weight: 600;}
.carte {border-radius: 16px; padding: 1.1rem 1.3rem; border: 2px solid; border-left-width: 10px; margin: .8rem 0 1rem;}
.carte .statut {font-size: 1.45rem; font-weight: 800; margin-bottom: .7rem; color: #1f2933;}
.carte .question {font-size: .95rem; font-weight: 700; margin-top: .8rem; text-transform: none;}
.carte .reponse {font-size: 1.1rem; color: #1f2933; line-height: 1.45;}
.carte .date {font-size: 2rem; font-weight: 800; line-height: 1.15;}
.carte .compte {font-size: 1.3rem; color: #1f2933; margin-top: .2rem;}
.carte .compte b {font-size: 3rem; font-weight: 800;}
.carte .detail {font-size: .95rem; color: #3e4c59; margin-top: .3rem;}
.badge {display: inline-block; padding: .1rem .6rem; border-radius: 999px; color: white; font-size: .8rem;
        font-weight: 700; margin: 0 .35rem .3rem 0; white-space: nowrap;}
.badge.contour {background: white !important; border: 1.5px solid #4a5563; color: #1f2933;}
.source {padding: .8rem 1rem; border: 1px solid #c3cad3; border-radius: 12px; margin: .5rem 0; background: white;}
.source .site {font-weight: 700; color: #1f2933; margin-right: .4rem;}
.source .texte {margin: .3rem 0; color: #1f2933;}
.source .citation {color: #3e4c59; font-style: italic; font-size: .95rem; margin-bottom: .3rem;}
[class*="st-key-carte_"] {border: 2px solid #c3cad3; border-radius: 14px; padding: .75rem; background: white;
                           margin-top: .4rem;}
[class*="st-key-carte_"][class*="_ok"] {border-color: #14713f; background: #f1f8f4;}
[class*="st-key-ok_"] button {background: #14713f !important; border-color: #14713f !important;}
[class*="st-key-ok_"] button p {color: white !important;}
.dommage {display: flex; gap: .9rem; align-items: flex-start;}
.note {color: #3e4c59; font-size: .95rem; line-height: 1.5; margin: .2rem 0 .7rem;}
.soustitre {font-size: 1.35rem; font-weight: 800; color: #1f2933; margin: 1rem 0 .3rem;}
.vignettes {display: flex; gap: .5rem; margin: .4rem 0;}
.vignettes figure {margin: 0; flex: 1; text-align: center; font-size: .9rem; color: #3e4c59;}
.vignettes img {width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 10px;}
.dommage img {width: 96px; height: 96px; object-fit: cover; border-radius: 10px; flex-shrink: 0;}
.dommage .vide {width: 96px; height: 96px; border-radius: 10px; flex-shrink: 0; background: #eef1f5;
                display: flex; align-items: center; justify-content: center; font-size: 2rem;}
.dommage .phrase {font-size: 1.08rem; color: #1f2933; line-height: 1.4;}
.dommage .phrase b {font-weight: 700;}
.dommage .infos {font-size: .9rem; color: #3e4c59; margin-top: .25rem;}
.dommage .ok {color: #14713f; font-weight: 700;}
.dommage .incertain {color: #a84e00; font-weight: 700;}
.piece {font-size: 1.25rem; font-weight: 800; color: #1f2933; margin: 1.2rem 0 0;}
.compteur {font-size: 1.1rem; margin: .3rem 0 .2rem;}
.lettre {font-family: Georgia, "Times New Roman", serif; background: white; color: #1f2933;
         border: 1px solid #c3cad3; border-radius: 12px; padding: 1.3rem; line-height: 1.55; font-size: .95rem;}
.pied {color: #3e4c59; font-size: .9rem; text-align: center; margin-top: 1rem; line-height: 1.6;}
@media (max-width: 640px) {
  .block-container {padding-left: 1rem; padding-right: 1rem;}
  h2.etape {font-size: 1.55rem;}
  .carte {padding: .9rem 1rem;}
  .carte .date {font-size: 1.7rem;}
  .dommage img, .dommage .vide {width: 72px; height: 72px;}
  [class*="st-key-carte_"] .stButton button {min-height: 2.8rem; padding: .3rem .7rem;}
  [class*="st-key-carte_"] .stButton button p {font-size: .95rem !important;}
  .lettre {padding: .9rem; font-size: .88rem;}
}
</style>
"""


# ---------------------------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------------------------
def t(cle, **valeurs):
    """Texte de l'interface dans la langue choisie."""
    texte = TEXTES[st.session_state.langue][cle]
    return texte.format(**valeurs) if valeurs and isinstance(texte, str) else texte


def initialiser_session():
    defauts = {
        "langue": "fr", "etape": 1, "commune": None, "radar": None, "demo_photos": False,
        "dommages": None, "miniatures": [], "prochain_id": 1, "edition": None, "ajout": False,
        "supprime": None, "version_tableau": 0, "resultat_lettre": None,
        "compteurs": {"analyses": 0, "lettres": 0, "photos": 0},
        "tech": {"radar": None, "photos": None, "lettre": None, "lignes_rejetees": 0, "erreurs": []},
    }
    for cle, valeur in {**defauts, **SAISIES}.items():
        st.session_state.setdefault(cle, valeur)


def garder_saisies():
    """Streamlit oublie la valeur d'un champ qui n'est plus affiché (quand on change d'étape).

    Réaffecter chaque valeur au début de la page la conserve : les infos saisies à l'étape 3
    sont encore là si l'on revient à l'étape 2, puis à l'étape 3.
    """
    for cle in SAISIES:
        st.session_state[cle] = st.session_state[cle]


def effacer_donnees():
    """Efface tout ce qui est personnel (les compteurs de la visite sont conservés)."""
    compteurs, langue = st.session_state.compteurs, st.session_state.langue
    for cle in list(st.session_state.keys()):
        del st.session_state[cle]
    st.session_state.compteurs, st.session_state.langue = compteurs, langue


def lancer_demo():
    """Bouton « Voir un exemple » : pré-remplit Martigues, les 3 photos et une personne fictive."""
    st.session_state.pop("choix_commune", None)
    st.session_state.update(DEMO)
    st.session_state.update(etape=1, demo_photos=True, lancer_analyse=True, radar=None, dommages=None,
                            miniatures=[], edition=None, ajout=False, supprime=None, resultat_lettre=None)


@st.cache_data(ttl=3600, show_spinner=False)
def suggestions_communes(nom, departement):
    params = {"nom": nom, "fields": "nom,code,codeDepartement,codesPostaux", "boost": "population", "limit": 8}
    if departement:
        params["codeDepartement"] = departement
    reponse = requests.get(GEO_API, params=params, timeout=10)
    reponse.raise_for_status()
    return reponse.json()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def radar_commune(code_insee, nom, departement):
    """Données publiques uniquement : mises en cache et partagées entre visiteurs pour économiser l'IA."""
    arretes = recuperer_arretes_catnat(code_insee)
    recherche = rechercher_actualites(nom, departement)
    return {"arretes": arretes, "resultat": analyser_situation(nom, arretes, recherche["resultats"])}


@st.cache_data(show_spinner=False)
def inventaire_demo():
    """Les photos de démo sont publiques : leur analyse est faite une fois puis réutilisée."""
    return analyser_photos(PHOTOS_DEMO)


def miniature(source):
    """Petite version JPEG d'une photo (chemin ou fichier envoyé), gardée en mémoire seulement."""
    if hasattr(source, "seek"):
        source.seek(0)
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((TAILLE_MINIATURE, TAILLE_MINIATURE))
        tampon = io.BytesIO()
        image.save(tampon, format="JPEG", quality=80)
    return tampon.getvalue()


@st.cache_data(show_spinner=False)
def miniature_demo(chemin):
    """Miniature d'une photo de démo (publique, donc mise en cache)."""
    return miniature(chemin)


def trier_arretes(arretes):
    """Renvoie (arrêtés au délai en cours, arrêtés des 12 derniers mois au délai dépassé), chacun (brut, calcul)."""
    en_cours, depasses = [], []
    il_y_a_un_an = date.today() - timedelta(days=365)
    for brut in arretes:
        calcul = calculer_delai_declaration(brut)
        if calcul["depasse"] is False:
            en_cours.append((brut, calcul))
        elif calcul["depasse"] and calcul["publication_jo"] > il_y_a_un_an:
            depasses.append((brut, calcul))
    en_cours.sort(key=lambda x: x[1]["date_limite"])
    depasses.sort(key=lambda x: x[1]["publication_jo"], reverse=True)
    return en_cours, depasses


def arrete_retenu(cas, arretes):
    """Cas A : l'arrêté au délai en cours ; cas E : le dernier arrêté expiré ; sinon None (pas encore d'arrêté)."""
    en_cours, depasses = trier_arretes(arretes)
    if cas == "A" and en_cours:
        return en_cours[0]
    if cas == "E" and depasses:
        return depasses[0]
    return None


def executer(action):
    """Exécute `action` ; en cas de problème, affiche un message simple (le détail va dans les infos techniques)."""
    try:
        return action()
    except LimiteTokensAtteinte:
        st.error(t("limite_tokens"))
    except Exception as erreur:  # réseau, service indisponible, réponse illisible...
        st.session_state.tech["erreurs"].append(str(erreur)[:300])
        st.error(t("erreur_technique"))
    return None


def note(texte):
    """Petit texte d'aide, gris foncé : plus lisible que st.caption pour une personne âgée."""
    st.markdown(f'<div class="note">{html.escape(texte)}</div>', unsafe_allow_html=True)


def valeur_en_texte(valeur):
    return f"{round(float(valeur)):,} €".replace(",", " ") if valeur is not None and not pd.isna(valeur) else A_COMPLETER


def dommages_vers_inventaire(dommages):
    """Les dégâts vérifiés par le sinistré, au format attendu par la lettre et le PDF."""
    return [{"zone": d["zone"] or A_COMPLETER, "objet": d["objet"], "dommage": d["dommage"] or A_COMPLETER,
             "certitude": d["certitude"], "photo": d["photo"], "valeur_estimee": valeur_en_texte(d["valeur"])}
            for d in dommages]


def nouveau_dommage(photo, zone, objet, dommage, certitude, valeur=None, relu=False):
    identifiant = st.session_state.prochain_id
    st.session_state.prochain_id += 1
    return {"id": identifiant, "photo": photo, "zone": zone, "objet": objet, "dommage": dommage,
            "certitude": certitude, "valeur": valeur, "relu": relu}


def _texte(valeur):
    return "" if valeur is None or (not isinstance(valeur, str) and pd.isna(valeur)) else str(valeur).strip()


# --- Actions sur la liste des dégâts (appelées par les boutons, avant le réaffichage de la page) ---
def trouver(identifiant):
    return next(d for d in st.session_state.dommages if d["id"] == identifiant)


def marquer_correct(identifiant):
    trouver(identifiant)["relu"] = True


def ouvrir_edition(identifiant):
    st.session_state.update(edition=identifiant, ajout=False)


def supprimer_dommage(identifiant):
    dommages = st.session_state.dommages
    position = next(i for i, d in enumerate(dommages) if d["id"] == identifiant)
    st.session_state.supprime = (position, dommages.pop(position))
    st.session_state.version_tableau += 1


def annuler_suppression():
    position, dommage = st.session_state.supprime
    st.session_state.dommages.insert(position, dommage)
    st.session_state.supprime = None
    st.session_state.version_tableau += 1


def lire_formulaire(prefixe):
    s = st.session_state
    return {"zone": s[f"{prefixe}_zone"].strip(), "objet": s[f"{prefixe}_objet"].strip(),
            "dommage": s[f"{prefixe}_dommage"].strip(), "valeur": s[f"{prefixe}_valeur"],
            "certitude": PROBABLE if s[f"{prefixe}_incertain"] else CERTAIN}


def enregistrer_edition(identifiant):
    champs = lire_formulaire(f"ed{identifiant}")
    if champs["objet"]:
        trouver(identifiant).update(champs, relu=True)  # modifier un dégât vaut vérification
        st.session_state.edition = None
        st.session_state.version_tableau += 1


def enregistrer_ajout():
    champs = lire_formulaire("aj")
    if champs["objet"]:
        st.session_state.dommages.append(nouveau_dommage(None, relu=True, **champs))
        st.session_state.ajout = False
        st.session_state.version_tableau += 1


def fermer_formulaires():
    st.session_state.update(edition=None, ajout=False)


# ---------------------------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------------------------
def afficher_entete():
    col_marque, col_langue = st.columns([4, 1.4], vertical_alignment="center")
    col_marque.markdown(f'<div class="marque"><span class="nom">🌊 30 Days</span>'
                        f'<span class="slogan">{html.escape(t("slogan"))}</span></div>', unsafe_allow_html=True)
    col_langue.radio("Langue / Language", ["fr", "en"], key="langue", horizontal=True, label_visibility="collapsed",
                     format_func=lambda l: {"fr": "🇫🇷 FR", "en": "🇬🇧 EN"}[l])
    if st.session_state.etape == 1:
        st.button(t("demo"), on_click=lancer_demo, help=t("demo_aide"), width="stretch")
    etape = st.session_state.etape
    st.markdown(f'<h2 class="etape">{html.escape(t("etape_n", n=etape, nom=t("etapes")[etape - 1]))}</h2>',
                unsafe_allow_html=True)
    st.progress(etape / 3)


def afficher_source(affirmation):
    niveau = affirmation["niveau"]
    lien = affirmation["source"]
    site = t("georisques") if niveau == "Géorisques" else (urlparse(lien).netloc.removeprefix("www.") or lien)
    badges = (f'<span class="badge" style="background:{COULEURS_BADGES.get(niveau, "#4a5563")}">'
              f'{html.escape(t("badges").get(niveau, niveau))}</span>')
    if affirmation["statut"] == NON_OFFICIEL:
        badges += f'<span class="badge contour">{html.escape(t("a_verifier"))}</span>'
    citation = (f'<div class="citation">« {html.escape(affirmation["citation"])} »</div>'
                if affirmation.get("citation") else "")
    st.markdown(
        f'<div class="source"><span class="site">{html.escape(site)}</span>{badges}'
        f'<div class="texte">{html.escape(affirmation["texte"])}</div>{citation}'
        f'<a href="{html.escape(lien)}" target="_blank" rel="noopener">{html.escape(t("voir_source"))} ↗</a></div>',
        unsafe_allow_html=True,
    )


def afficher_radar():
    """La carte répond à 3 questions, avec des textes écrits par le code (jamais par l'IA)."""
    donnees, commune = st.session_state.radar, st.session_state.commune
    resultat = donnees["resultat"]
    cas = resultat["cas"]
    en_cours, depasses = trier_arretes(donnees["arretes"])
    arrete = arrete_retenu(cas, donnees["arretes"])
    couleur = COULEURS_CAS[cas]
    faits = {"commune": commune["nom"], "type": "", "jo": "", "limite": ""}
    if arrete:
        calcul = arrete[1]
        faits.update(type=calcul["type"].lower(), jo=_format(calcul["publication_jo"]),
                     limite=_format(calcul["date_limite"]))

    compte = ""
    if cas == "A" and arrete:
        jours = arrete[1]["jours_restants"]
        compte = f'<div class="compte">{t("compte_1") if jours <= 0 else t("compte", n=jours)}</div>'
    e = html.escape
    st.markdown(
        f'<div class="carte" style="border-color:{couleur}; background:{couleur}0f">'
        f'<div class="statut" style="color:{couleur}">{e(t("statuts")[cas])}</div>'
        f'<div class="question" style="color:{couleur}">{e(t("q_situation"))}</div>'
        f'<div class="reponse">{e(t("situation")[cas].format(**faits))}</div>'
        f'<div class="question" style="color:{couleur}">{e(t("q_faire"))}</div>'
        f'<div class="reponse"><b>{e(t("faire")[cas])}</b></div>'
        f'<div class="question" style="color:{couleur}">{e(t("q_date"))}</div>'
        f'<div class="date" style="color:{couleur}">{e(t("date")[cas].format(**faits))}</div>{compte}'
        f'<div class="detail">{e(t("date_detail")[cas].format(**faits))}</div></div>',
        unsafe_allow_html=True,
    )

    if cas != "E" and depasses:
        c = depasses[0][1]
        st.info(t("info_depasse", type=c["type"].lower(), jo=_format(c["publication_jo"]),
                  limite=_format(c["date_limite"])))

    with st.expander(t("pourquoi")):
        if t("sources_fr"):
            note(t("sources_fr"))
        if resultat["explication"] and not resultat["corrections"]:
            st.markdown(f"**{t('resume_ia')}** {resultat['explication']}")
        for affirmation in resultat["affirmations"]:
            afficher_source(affirmation)


def afficher_carte_dommage(d):
    """Une carte par dégât : miniature, une phrase, et les boutons Correct / Modifier / Supprimer."""
    miniatures = st.session_state.miniatures
    if d["photo"] and d["photo"] <= len(miniatures):
        image = f'<img src="data:image/jpeg;base64,{base64.b64encode(miniatures[d["photo"] - 1]).decode()}" alt="">'
        origine = t("photo_n", n=d["photo"])
    else:
        image, origine = '<div class="vide">📝</div>', t("sans_photo")
    infos = [html.escape(origine)]
    if d["valeur"] is not None and not pd.isna(d["valeur"]):
        infos.append(html.escape(t("valeur_txt", v=valeur_en_texte(d["valeur"]))))
    if d["certitude"] == PROBABLE:
        infos.append(f'<span class="incertain">{html.escape(t("a_confirmer"))}</span>')
    if d["relu"]:
        infos.append(f'<span class="ok">{html.escape(t("verifie"))}</span>')
    dommage = d["dommage"].rstrip(".")
    phrase = f"<b>{html.escape(d['objet'][:1].upper() + d['objet'][1:])}</b>" + (f" : {html.escape(dommage)}." if dommage else "")
    # La clé du conteneur devient sa classe CSS : bordure verte quand le dégât est vérifié
    with st.container(key=f"carte_{d['id']}{'_ok' if d['relu'] else ''}"):
        st.markdown(f'<div class="dommage">{image}<div><div class="phrase">{phrase}</div>'
                    f'<div class="infos">{" · ".join(infos)}</div></div></div>', unsafe_allow_html=True)
        with st.container(horizontal=True, gap="small"):
            if not d["relu"]:
                st.button(t("correct"), key=f"ok_{d['id']}", on_click=marquer_correct, args=(d["id"],))
            st.button(t("modifier"), key=f"mod_{d['id']}", on_click=ouvrir_edition, args=(d["id"],))
            st.button(t("supprimer"), key=f"sup_{d['id']}", on_click=supprimer_dommage, args=(d["id"],))


def formulaire_dommage(prefixe, d, au_clic, args=()):
    """Formulaire de modification (d = le dégât) ou d'ajout (d = None)."""
    d = d or {"zone": "", "objet": "", "dommage": "", "valeur": None, "certitude": CERTAIN}
    with st.form(f"form_{prefixe}", border=True):
        st.text_input(t("champ_zone"), value=d["zone"], key=f"{prefixe}_zone")
        st.text_input(t("champ_objet"), value=d["objet"], key=f"{prefixe}_objet")
        st.text_area(t("champ_dommage"), value=d["dommage"], key=f"{prefixe}_dommage", height=90)
        valeur = None if d["valeur"] is None or pd.isna(d["valeur"]) else float(d["valeur"])
        st.number_input(t("champ_valeur"), value=valeur, min_value=0.0, step=10.0, format="%.0f",
                        key=f"{prefixe}_valeur", help=t("champ_valeur_aide"))
        st.checkbox(t("champ_incertain"), value=d["certitude"] == PROBABLE, key=f"{prefixe}_incertain")
        with st.container(horizontal=True, gap="small"):
            envoye = st.form_submit_button(t("enregistrer"), type="primary", on_click=au_clic, args=args)
            st.form_submit_button(t("annuler"), on_click=fermer_formulaires)
    if envoye and not st.session_state.get(f"{prefixe}_objet", "").strip():
        st.warning(t("objet_obligatoire"))


def afficher_liste_dommages():
    dommages = st.session_state.dommages
    if st.session_state.supprime:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(t("supprime", objet=st.session_state.supprime[1]["objet"]))
            st.button(t("annuler_suppression"), on_click=annuler_suppression)
    if not dommages:
        st.info(t("liste_vide"))
    # Regroupés par pièce, dans l'ordre où les pièces apparaissent
    for piece in dict.fromkeys(d["zone"] for d in dommages):
        st.markdown(f'<div class="piece">{html.escape((piece or "—").capitalize())}</div>', unsafe_allow_html=True)
        for d in (d for d in dommages if d["zone"] == piece):
            if st.session_state.edition == d["id"]:
                formulaire_dommage(f"ed{d['id']}", d, enregistrer_edition, (d["id"],))
            else:
                afficher_carte_dommage(d)
    st.write("")
    if st.session_state.ajout:
        formulaire_dommage("aj", None, enregistrer_ajout)
    else:
        st.button(t("ajouter"), on_click=lambda: st.session_state.update(ajout=True, edition=None), width="stretch")


def afficher_tableau_dommages():
    note(t("tableau_aide"))
    noms = t("colonnes")
    colonnes = ["photo", "zone", "objet", "dommage", "certitude", "valeur"]
    df = pd.DataFrame([{c: d[c] for c in colonnes} for d in st.session_state.dommages], columns=colonnes)
    df = df.astype({"photo": "Int64", "valeur": "float64"})
    # Nouvelle clé à chaque changement venu des cartes : le tableau repart des données à jour
    edite = st.data_editor(
        df, key=f"tableau_{st.session_state.version_tableau}", num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "photo": st.column_config.NumberColumn(noms["photo"], min_value=1, step=1, width="small"),
            "zone": st.column_config.TextColumn(noms["zone"]),
            "objet": st.column_config.TextColumn(noms["objet"], required=True),
            "dommage": st.column_config.TextColumn(noms["dommage"], width="large"),
            "certitude": st.column_config.SelectboxColumn(noms["certitude"], options=[CERTAIN, PROBABLE]),
            "valeur": st.column_config.NumberColumn(noms["valeur"], min_value=0, step=10, format="%d €"),
        },
    )
    if st.button(t("enregistrer_tableau"), width="stretch"):
        nouveaux = []
        for _, r in edite.iterrows():
            if not _texte(r["objet"]):
                continue  # ligne vide : ignorée
            photo = int(r["photo"]) if _texte(r["photo"]) else None
            # Une ligne ajoutée par le sinistré lui-même est considérée comme certaine
            certitude = r["certitude"] if r["certitude"] in (CERTAIN, PROBABLE) else CERTAIN
            valeur = None if pd.isna(r["valeur"]) else float(r["valeur"])
            nouveaux.append(nouveau_dommage(photo, _texte(r["zone"]), _texte(r["objet"]), _texte(r["dommage"]),
                                            certitude, valeur, relu=True))
        st.session_state.update(dommages=nouveaux, supprime=None, edition=None, ajout=False)
        st.session_state.version_tableau += 1
        st.rerun()


# ---------------------------------------------------------------------------------------------
# Les 3 étapes
# ---------------------------------------------------------------------------------------------
def etape_commune():
    st.markdown(f'<div class="intro">{html.escape(t("intro_1"))}</div>', unsafe_allow_html=True)
    col_nom, col_dep = st.columns([3, 2])
    nom = col_nom.text_input(t("commune"), key="saisie_commune", placeholder="Martigues").strip()
    dep = col_dep.text_input(t("departement"), key="saisie_dep", placeholder="13", max_chars=3,
                             help=t("departement_aide")).strip()

    suggestions = []
    if len(nom) >= 2:
        try:
            suggestions = suggestions_communes(nom, dep)
        except requests.RequestException:
            st.warning(t("erreur_geo"))
        else:
            if not suggestions:
                st.info(t("aucune_commune"))
    choix = None
    if suggestions:
        choix = st.selectbox(
            t("choisir_commune"), suggestions, key="choix_commune",
            format_func=lambda c: f"{c['nom']} ({c['codeDepartement']}) · {', '.join(c.get('codesPostaux', [])[:3])}",
        )

    demande_demo = st.session_state.pop("lancer_analyse", False)
    deja_analyse = st.session_state.radar is not None
    clic = st.button(t("analyser"), type="secondary" if deja_analyse else "primary", width="stretch")
    if clic and not choix:
        st.warning(t("choisir_d_abord"))
    if (clic or demande_demo) and choix:
        if st.session_state.compteurs["analyses"] >= LIMITES["analyses"]:
            st.error(t("limite_analyses"))
        else:
            with st.spinner(t("analyse_en_cours")):
                donnees = executer(lambda: radar_commune(choix["code"], choix["nom"], choix["codeDepartement"]))
            if donnees:
                st.session_state.compteurs["analyses"] += 1
                st.session_state.commune = {"nom": choix["nom"], "code": choix["code"],
                                            "departement": choix["codeDepartement"]}
                st.session_state.radar = donnees
                st.session_state.tech["radar"] = donnees["resultat"]["tokens"]["total_tokens"]
                st.session_state.resultat_lettre = None
                st.rerun()  # réaffiche la page : le bouton « Continuer » devient la seule action principale

    if st.session_state.radar:
        afficher_radar()
        if st.button(t("continuer_degats"), type="primary", width="stretch"):
            st.session_state.etape = 2
            st.rerun()


def etape_degats():
    compteurs = st.session_state.compteurs
    dommages = st.session_state.dommages

    if dommages is None:  # avant l'analyse : choisir les photos
        st.markdown(f'<div class="intro">{html.escape(t("intro_2"))}</div>', unsafe_allow_html=True)
        note(t("prive"))
        restantes = LIMITES["photos"] - compteurs["photos"]
        fichiers = []
        if st.session_state.demo_photos:
            st.info(t("photos_demo_info"))
            vignettes = "".join(
                f'<figure><img src="data:image/jpeg;base64,{base64.b64encode(miniature_demo(str(c))).decode()}" alt="">'
                f'<figcaption>{html.escape(t("photo_n", n=i))}</figcaption></figure>'
                for i, c in enumerate(PHOTOS_DEMO, start=1))
            st.markdown(f'<div class="vignettes">{vignettes}</div>', unsafe_allow_html=True)
            note(t("credits_photos"))
            st.button(t("utiliser_mes_photos"), on_click=lambda: st.session_state.update(demo_photos=False))
        else:
            fichiers = st.file_uploader(t("ajouter_photos"), type=["jpg", "jpeg", "png", "webp"],
                                        accept_multiple_files=True, help=t("aide_photos", n=restantes)) or []
        st.text_area(t("description"), key="description", placeholder=t("description_exemple"))

        nombre = len(PHOTOS_DEMO) if st.session_state.demo_photos else len(fichiers)
        if nombre and st.button(t("analyser_photos", n=nombre), type="primary", width="stretch"):
            if nombre > LIMITES["photos"]:
                st.error(t("trop_de_photos"))
            elif not st.session_state.demo_photos and nombre > restantes:
                st.error(t("limite_photos", n=restantes))
            else:
                sources = PHOTOS_DEMO if st.session_state.demo_photos else fichiers
                with st.spinner(t("analyse_photos_en_cours")):
                    analyse = executer(inventaire_demo if st.session_state.demo_photos
                                       else lambda: analyser_photos(fichiers))
                if analyse:
                    if not st.session_state.demo_photos:  # les photos de démo, déjà analysées, ne comptent pas
                        compteurs["photos"] += nombre
                    st.session_state.update(
                        miniatures=[miniature_demo(str(s)) if st.session_state.demo_photos else miniature(s)
                                    for s in sources], supprime=None, edition=None, ajout=False,
                        dommages=[nouveau_dommage(l["photo"], l["zone"], l["objet"], l["dommage"], l["certitude"])
                                  for l in analyse["inventaire"]],
                    )
                    st.session_state.tech.update(photos=analyse["tokens"]["total_tokens"],
                                                 lignes_rejetees=len(analyse["rejetees"]))
                    st.rerun()
        if not nombre:
            st.button(t("sans_photos"), on_click=lambda: st.session_state.update(dommages=[]), width="stretch")
    else:  # après l'analyse : vérifier chaque dégât
        st.markdown(f'<div class="soustitre">{html.escape(t("verifier_titre"))}</div>', unsafe_allow_html=True)
        st.markdown(t("verifier_aide"))
        relus = sum(d["relu"] for d in dommages)
        if dommages:
            st.markdown(f'<div class="compteur">{t("verifies", n=relus, total=len(dommages))}</div>',
                        unsafe_allow_html=True)
            st.progress(relus / len(dommages))
        onglet_liste, onglet_tableau = st.tabs([t("onglet_liste"), t("onglet_tableau")])
        with onglet_liste:
            afficher_liste_dommages()
        with onglet_tableau:
            afficher_tableau_dommages()
        st.text_area(t("description"), key="description", placeholder=t("description_exemple"))

    dommages = st.session_state.dommages or []
    tout_relu = all(d["relu"] for d in dommages)
    pret = (dommages and tout_relu) or (not dommages and st.session_state.description.strip())
    if dommages and tout_relu:
        st.success(t("tout_verifie"))
    if pret:
        if st.button(t("continuer_lettre"), type="primary", width="stretch"):
            fermer_formulaires()
            st.session_state.etape = 3
            st.rerun()
    elif st.session_state.dommages is not None:
        note(t("reste_a_verifier") if dommages else t("rien_a_declarer"))
    if st.button(t("retour"), width="stretch"):
        st.session_state.etape = 1
        st.rerun()


def etape_lettre():
    donnees, commune = st.session_state.radar, st.session_state.commune
    cas = donnees["resultat"]["cas"]
    arrete = arrete_retenu(cas, donnees["arretes"])
    resultat = st.session_state.resultat_lettre

    if resultat is None:
        st.markdown(f'<div class="intro">{html.escape(t("intro_3"))}</div>', unsafe_allow_html=True)
        if t("lettre_en_francais"):
            st.info(t("lettre_en_francais"))
        if arrete:
            st.info(t("lettre_avec_arrete", jo=_format(arrete[1]["publication_jo"])))
        else:
            st.info(t("lettre_sans_arrete"))
        if cas == "E":
            st.warning(t("alerte_depasse"))

        with st.form("formulaire_lettre", border=False):
            st.text_input(t("nom"), key="f_nom")
            st.text_input(t("adresse"), key="f_adresse")
            st.text_input(t("assureur"), key="f_assureur")
            st.text_input(t("adresse_assureur"), key="f_adresse_assureur")
            st.text_input(t("contrat"), key="f_contrat", help=t("aide_contrat"))
            if not arrete:
                st.selectbox(t("type_evenement"), TYPES_EVENEMENT, key="f_type", accept_new_options=True,
                             placeholder=t("type_choisir"))
                st.date_input(t("date_debut"), key="f_debut", format="DD/MM/YYYY")
                st.date_input(t("date_fin"), key="f_fin", format="DD/MM/YYYY")
            note(t("vide_a_completer"))
            envoyer = st.form_submit_button(t("generer"), type="primary", width="stretch")

        if envoyer:
            if st.session_state.compteurs["lettres"] >= LIMITES["lettres"]:
                st.error(t("limite_lettres"))
            else:
                s = st.session_state
                sinistre = {
                    "nom": s.f_nom, "adresse": s.f_adresse, "assureur": s.f_assureur,
                    "adresse_assureur": s.f_adresse_assureur, "numero_contrat": s.f_contrat,
                    "description_degats": s.description, "commune": commune["nom"],
                    "type_evenement": s.f_type, "date_debut": s.f_debut, "date_fin": s.f_fin,
                }
                inventaire = dommages_vers_inventaire(s.dommages or []) or None
                with st.spinner(t("generation")):
                    resultat = executer(lambda: generer_lettre(arrete[0] if arrete else None, sinistre, inventaire))
                if resultat:
                    s.compteurs["lettres"] += 1
                    resultat["pdf"] = lettre_en_pdf(resultat["lettre"], inventaire)
                    resultat["inventaire"] = inventaire
                    s.resultat_lettre = resultat
                    s.tech["lettre"] = resultat["tokens"]["total_tokens"]
                    st.rerun()
    else:
        st.success(t("lettre_prete"))
        st.download_button(t("telecharger"), data=resultat["pdf"], file_name="declaration_sinistre.pdf",
                           mime="application/pdf", type="primary", width="stretch")
        st.markdown(t("a_envoyer"))
        if resultat["secours"]:  # l'IA a échoué : lettre du modèle fixe, signalée discrètement
            note(t("version_simplifiee"))
        with st.expander(t("lire_lettre")):
            corps = resultat["lettre"].split(SEPARATEUR_ANNEXE)[0].strip()
            st.markdown(f'<div class="lettre">{html.escape(corps).replace(chr(10), "<br>")}</div>',
                        unsafe_allow_html=True)
            if resultat["inventaire"]:
                st.markdown(t("page_2", n=len(resultat["inventaire"])))

        blocs = checklist_pieces(arrete[1] if arrete else None, bool(resultat["inventaire"]), st.session_state.langue)
        for cle, titre in t("blocs").items():
            st.markdown(f'<div class="soustitre">{html.escape(titre)}</div>', unsafe_allow_html=True)
            for numero, piece in enumerate(blocs[cle]):
                st.checkbox(piece, key=f"piece_{cle}_{numero}")
        st.write("")
        st.button(t("modifier_infos"), on_click=lambda: st.session_state.update(resultat_lettre=None), width="stretch")

    if st.button(t("retour"), width="stretch"):
        st.session_state.etape = 2
        st.rerun()


def afficher_bas_de_page():
    st.divider()
    with st.expander(t("comment")):
        col_code, col_ia = st.columns(2)
        with col_code:
            st.markdown(t("comment_code"))
            st.markdown("\n".join(f"- {ligne}" for ligne in t("comment_code_liste")))
        with col_ia:
            st.markdown(t("comment_ia"))
            st.markdown("\n".join(f"- {ligne.format(radar=MODELE_RADAR, vision=MODELE_VISION, lettre=MODELE_LETTRE)}"
                                  for ligne in t("comment_ia_liste")))
        st.info(t("comment_regle"))

        # Les infos techniques sont ici, et nulle part ailleurs
        st.markdown(t("technique"))
        tech, radar = st.session_state.tech, st.session_state.radar
        lignes = []
        if radar:
            r = radar["resultat"]
            lignes.append(t("tech_cas", cas=r["cas"], libelle=r["libelle"]))
        lignes.append(t("tech_tokens", radar=tech["radar"] or "–", photos=tech["photos"] or "–",
                        lettre=tech["lettre"] or "–"))
        if tech["lignes_rejetees"]:
            lignes.append(t("tech_lignes_rejetees", n=tech["lignes_rejetees"]))
        lettre = st.session_state.resultat_lettre
        if lettre:
            lignes.append(t("tech_brouillons", n=len(lettre["rejets"]), secours=t("oui") if lettre["secours"] else t("non")))
            lignes += [f"   - {html.escape(rejet)}" for rejet in lettre["rejets"]]
        st.markdown("\n".join(f"- {ligne}" if not ligne.startswith("   ") else ligne for ligne in lignes))
        if radar:
            r = radar["resultat"]
            st.markdown(t("tech_corrections") if r["corrections"] else t("tech_aucune_correction"))
            if r["corrections"]:
                st.markdown("\n".join(f"- {c}" for c in r["corrections"]))
            if r["rejetees"]:
                st.markdown(t("tech_rejetees"))
                st.markdown("\n".join(f"- {x['raison']} ({x['source'] or '—'})" for x in r["rejetees"]))
        if tech["erreurs"]:
            st.markdown(t("tech_erreurs"))
            st.markdown("\n".join(f"- `{x}`" for x in tech["erreurs"]))

    c = st.session_state.compteurs
    st.button(t("effacer"), on_click=effacer_donnees, width="stretch")
    st.markdown(
        f'<div class="pied">{html.escape(t("confidentialite"))}<br>{html.escape(t("avertissement"))}<br>'
        f'{html.escape(t("session", a=c["analyses"], l=c["lettres"], p=c["photos"]))}<br>'
        f'{html.escape(t("pied"))} · <a href="{URL_DEPOT}" target="_blank" rel="noopener">{t("code_source")}</a></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------------------------
st.set_page_config(page_title="30 Days", page_icon="🌊", layout="centered", initial_sidebar_state="collapsed")
initialiser_session()
garder_saisies()
st.markdown(CSS, unsafe_allow_html=True)

# Sans commune analysée, on ne peut pas aller plus loin que l'étape 1
if st.session_state.etape > 1 and not st.session_state.radar:
    st.session_state.etape = 1
afficher_entete()
{1: etape_commune, 2: etape_degats, 3: etape_lettre}[st.session_state.etape]()
afficher_bas_de_page()

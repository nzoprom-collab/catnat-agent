"""30 Days : interface web (Streamlit) pour les sinistrés d'une catastrophe naturelle en France.

Lancer :  .venv/bin/streamlit run app.py

Confidentialité : rien de personnel n'est écrit sur le disque. Les photos et les informations du
sinistré restent en mémoire, dans la session du navigateur, et disparaissent à la fermeture de la page.
Seuls des résultats publics (arrêtés Géorisques, recherches web) sont mis en cache.
"""

import html
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
import streamlit as st

from catnat import GEO_API, _format, calculer_delai_declaration, recuperer_arretes_catnat
from lettre import MODELE_LETTRE, NOTE_ANNEXE, SEPARATEUR_ANNEXE, TITRE_ANNEXE, A_COMPLETER, generer_lettre
from llm import LimiteTokensAtteinte
from pdf import lettre_en_pdf
from photos import CERTAIN, MODELE_VISION, PROBABLE, analyser_photos
from radar import (AUTRE_SITE, MODELE_RADAR, NON_OFFICIEL, OFFICIEL_LOCAL, PRESSE, RESEAU_SOCIAL,
                   analyser_situation, rechercher_actualites)

DOSSIER = Path(__file__).parent
PHOTOS_DEMO = sorted((DOSSIER / "exemples").glob("photo*.jpg"))
URL_DEPOT = "https://github.com/nzoprom-collab/catnat-agent"
LIMITES = {"analyses": 3, "lettres": 2, "photos": 6}  # par session, pour protéger la démo publique

# Données FICTIVES pré-remplies par le bouton « Essayer la démo »
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

# ---------------------------------------------------------------------------------------------
# Textes de l'interface (français / anglais). La lettre, elle, est toujours en français.
# ---------------------------------------------------------------------------------------------
TEXTES = {
    "fr": {
        "slogan": "Ne ratez plus jamais votre délai de déclaration",
        "demo": "✨ Essayer la démo (Martigues + 3 photos)",
        "demo_aide": "Pré-remplit une commune réelle (Martigues, 13) et 3 photos d'exemple. Le sinistré est fictif.",
        "confidentialite": "🔒 **Confidentialité** : vos photos et informations personnelles ne sont jamais enregistrées sur le serveur. "
                           "Elles restent en mémoire le temps de votre visite et disparaissent quand vous fermez la page. "
                           "Les photos sont transmises à l'IA (Nebius) uniquement pour être analysées.",
        "avertissement": "⚖️ Outil d'aide : il ne remplace pas un conseil juridique. Vérifiez toujours votre contrat et contactez votre assureur.",
        "etapes": ["Ma commune", "Mes dégâts", "Ma lettre"],
        "etape_n": "Étape {n} sur 3 · {nom}",
        "commune": "Commune",
        "departement": "Département",
        "departement_aide": "Numéro du département (ex. 13). Facultatif, mais utile si plusieurs communes portent le même nom.",
        "choisir_commune": "Suggestions (geo.api.gouv.fr)",
        "aucune_commune": "Aucune commune trouvée. Vérifiez l'orthographe ou le département.",
        "erreur_geo": "La recherche de communes ne répond pas pour l'instant. Réessayez dans un instant.",
        "analyser": "🔍 Analyser ma commune",
        "analyse_en_cours": "Analyse en cours : arrêtés officiels, actualité, puis classement par l'IA (≈ 30 s)…",
        "cas": "Cas {cas}",
        "libelles": {
            "A": "Arrêté officiel publié : délai de déclaration en cours",
            "B": "Arrêté annoncé dans l'actualité, pas encore dans la base officielle",
            "C": "Demande de reconnaissance en cours, pas encore d'arrêté",
            "E": "Arrêté publié, délai de déclaration dépassé",
            "D": "Aucune procédure récente détectée",
        },
        "jours_restants": "jours pour déclarer vos dégâts",
        "jour_restant": "jour pour déclarer vos dégâts",
        "avant_le": "Date limite prudente : <b>{date}</b> (publication au Journal officiel + 29 jours)",
        "depasse_le": "La date limite était le <b>{date}</b>",
        "explication_ia": "🤖 Explication rédigée par l'IA",
        "verifications": "🛡️ Vérifications faites par le code",
        "corrections": "Le code a corrigé le classement de l'IA :",
        "rejetees": "Affirmations de l'IA rejetées :",
        "aucune_correction": "Aucune correction : le classement de l'IA est cohérent avec les données et les sources vérifiées.",
        "info_depasse": "ℹ️ Autre arrêté pour cette commune : « {type} », publié au JO le {jo}. Son délai de déclaration a expiré le {limite}.",
        "sources": "Sources",
        "sources_fr": "",
        "badges": {"Géorisques": "Géorisques · officiel", OFFICIEL_LOCAL: "officiel local", PRESSE: "presse",
                   RESEAU_SOCIAL: "réseau social", AUTRE_SITE: "autre site"},
        "a_verifier": "non officiel, à vérifier",
        "continuer_degats": "Continuer : mes dégâts →",
        "continuer_lettre": "Continuer : ma lettre →",
        "retour": "← Retour",
        "photos_demo_info": "📸 Démo : 3 photos d'exemple libres de droits (inondations aux États-Unis). Vous pouvez aussi envoyer les vôtres.",
        "credits_photos": "Crédits : B137 (CC0), King Prince (CC BY 2.0), Infrogmation (CC BY 2.5), via Wikimedia Commons. [Détails]({url}/blob/main/exemples/CREDITS.md)",
        "utiliser_mes_photos": "Utiliser mes propres photos",
        "ajouter_photos": "Ajoutez des photos de vos dégâts (6 maximum)",
        "aide_photos": "JPG, PNG ou WEBP. Photos restantes pour cette session : {n}.",
        "description": "Décrivez vos dégâts avec vos mots (facultatif)",
        "description_exemple": "Ex. : l'eau est montée de 50 cm dans le salon, la chaudière ne fonctionne plus…",
        "analyser_photos": "🔍 Analyser mes {n} photo(s)",
        "analyse_photos_en_cours": "L'IA regarde vos photos une par une (≈ 20 s par photo)…",
        "trop_de_photos": "6 photos maximum à la fois.",
        "inventaire": "Inventaire des dommages",
        "inventaire_aide": "Relisez chaque ligne : corrigez, supprimez (case à gauche puis 🗑️) ou ajoutez une ligne (en bas du tableau). "
                           "Remplissez la valeur estimée si vous la connaissez.",
        "photos_numeros": "Numéros des photos : {liste}",
        "lignes_rejetees": "{n} ligne(s) proposée(s) par l'IA rejetée(s) par le code (champ manquant, prix, numéro de photo invalide…).",
        "inventaire_manuel": "✍️ Saisir l'inventaire à la main",
        "colonnes": {"photo": "Photo", "zone": "Pièce", "objet": "Objet", "dommage": "Dommage constaté",
                     "certitude": "Certitude", "valeur": "Valeur estimée (€)"},
        "relu": "✅ J'ai relu l'inventaire",
        "relu_ok": "Inventaire validé : {n} ligne(s).",
        "modifs_non_validees": "Vous avez modifié l'inventaire : cliquez à nouveau sur « J'ai relu l'inventaire ».",
        "relire_obligatoire": "Relisez l'inventaire et cliquez sur « J'ai relu l'inventaire » pour continuer.",
        "rien_a_declarer": "Ajoutez des photos, une description ou une ligne d'inventaire pour continuer.",
        "lettre_avec_arrete": "📄 La lettre citera l'arrêté officiel **{ref}**, publié au Journal officiel le **{jo}**.",
        "lettre_sans_arrete": "📄 Aucun arrêté n'est encore publié : la lettre déclare vos dégâts **dès maintenant**, sans attendre. "
                              "Indiquez le type d'événement et sa date.",
        "lettre_en_francais": "",
        "alerte_depasse": "⚠️ Le délai légal est dépassé. Contactez votre assureur immédiatement en expliquant votre situation.",
        "nom": "Nom et prénom",
        "adresse": "Adresse du logement sinistré",
        "assureur": "Assureur",
        "adresse_assureur": "Adresse de l'assureur",
        "contrat": "Numéro de contrat",
        "type_evenement": "Type d'événement",
        "type_exemple": "Ex. : inondations et coulées de boue",
        "date_debut": "Date de l'événement (début)",
        "date_fin": "Date de fin (facultatif)",
        "vide_a_completer": "Un champ vide apparaîtra comme [À COMPLÉTER] dans la lettre.",
        "generer": "✍️ Générer ma lettre",
        "generation": "L'IA rédige le corps de la lettre, le code vérifie et insère les faits (≈ 30 s)…",
        "apercu": "Aperçu de la lettre",
        "telecharger": "⬇️ Télécharger la lettre (PDF)",
        "a_envoyer": "À envoyer en **lettre recommandée avec accusé de réception**, après relecture.",
        "checklist": "Pièces à joindre ou à préparer",
        "checklist_fr": "",
        "brouillons_refuses": "{n} brouillon(s) de l'IA refusé(s) par le code avant la version finale.",
        "version_simplifiee": "ℹ️ Version simplifiée : cette lettre a été rédigée à partir d'un modèle fixe. Relisez-la et complétez-la si besoin.",
        "cout": "Coût de cette étape : {tokens} tokens",
        "limite_analyses": "Limite atteinte : 3 analyses de commune par session (démo publique). Revenez plus tard.",
        "limite_lettres": "Limite atteinte : 2 lettres par session (démo publique). Revenez plus tard.",
        "limite_photos": "Limite atteinte : 6 photos par session (démo publique). Il vous en reste {n}.",
        "limite_tokens": "Le budget global d'IA de cette démo est épuisé (garde-fou anti-dépense). Merci de votre compréhension.",
        "erreur_technique": "Un problème technique est survenu : {detail}. Réessayez dans un instant.",
        "comment": "🧭 Comment ça marche ?",
        "comment_code": "#### 🧮 Fait par le code (fiable, vérifiable)",
        "comment_code_liste": [
            "**Faits officiels** : arrêtés de catastrophe naturelle (API Géorisques), communes (geo.api.gouv.fr)",
            "**Dates et délais** : date limite prudente = publication au Journal officiel + 29 jours (la loi accorde 30 jours, art. L125-2 du Code des assurances)",
            "**Vérification des sources web** : URL réellement trouvée, citation présente mot pour mot, niveau du site, nom de la commune",
            "**Dernier mot sur le cas** A/B/C/E/D, et tous les **conseils** affichés",
            "**Lettre** : en-tête, objet, dates, références, insérés par le code ; le brouillon de l'IA est refusé s'il invente un chiffre ou une date",
            "**Garde-fous** : budget de tokens, limites par session",
        ],
        "comment_ia": "#### 🤖 Fait par l'IA (NVIDIA Nemotron, via Nebius)",
        "comment_ia_liste": [
            "**Classement de la situation** à partir des arrêtés et de l'actualité : `{radar}`",
            "**Lecture des photos** et inventaire des dommages visibles : `{vision}`",
            "**Rédaction du corps de la lettre**, avec des étiquettes que le code remplit : `{lettre}`",
            "**Recherche web** : Tavily (2 recherches par commune, mises en cache 24 h)",
        ],
        "comment_regle": "**Règle d'or** : l'IA n'invente jamais un fait. Elle rédige et classe ; le code fournit et vérifie les faits.",
        "session": "Ma session",
        "restant": "Analyses : {a}/3 · Lettres : {l}/2 · Photos : {p}/6",
        "effacer": "🧹 Effacer mes données et recommencer",
        "pied": "Prototype réalisé pour le hackathon Nebius x NVIDIA · NVIDIA Nemotron · Tavily · données Géorisques et geo.api.gouv.fr",
        "code_source": "code source",
    },
    "en": {
        "slogan": "Never miss your disaster claim deadline",
        "demo": "✨ Try the demo (Martigues + 3 photos)",
        "demo_aide": "Pre-fills a real town (Martigues, 13) and 3 sample photos. The policyholder is fictitious.",
        "confidentialite": "🔒 **Privacy**: your photos and personal details are never stored on the server. "
                           "They stay in memory during your visit and disappear when you close the page. "
                           "Photos are sent to the AI (Nebius) only to be analysed.",
        "avertissement": "⚖️ Assistance tool: it does not replace legal advice. Always check your policy and contact your insurer.",
        "etapes": ["My town", "My damage", "My letter"],
        "etape_n": "Step {n} of 3 · {nom}",
        "commune": "Town (commune)",
        "departement": "Département",
        "departement_aide": "French département number (e.g. 13). Optional, but useful when several towns share a name.",
        "choisir_commune": "Suggestions (geo.api.gouv.fr)",
        "aucune_commune": "No town found. Check the spelling or the département.",
        "erreur_geo": "The town search is not responding right now. Please try again in a moment.",
        "analyser": "🔍 Analyse my town",
        "analyse_en_cours": "Analysing: official decrees, news, then AI classification (≈ 30 s)…",
        "cas": "Case {cas}",
        "libelles": {
            "A": "Official decree published: claim deadline still open",
            "B": "Decree announced in the news, not yet in the official database",
            "C": "Recognition request in progress, no decree yet",
            "E": "Decree published, claim deadline has passed",
            "D": "No recent procedure detected",
        },
        "jours_restants": "days left to report your damage",
        "jour_restant": "day left to report your damage",
        "avant_le": "Safe deadline: <b>{date}</b> (publication in the Official Journal + 29 days)",
        "depasse_le": "The deadline was <b>{date}</b>",
        "explication_ia": "🤖 Explanation written by the AI (in French)",
        "verifications": "🛡️ Checks performed by the code",
        "corrections": "The code corrected the AI's classification:",
        "rejetees": "AI statements rejected:",
        "aucune_correction": "No correction: the AI's classification is consistent with the data and the verified sources.",
        "info_depasse": "ℹ️ Another decree for this town: “{type}”, published in the Official Journal on {jo}. Its claim deadline expired on {limite}.",
        "sources": "Sources",
        "sources_fr": "Sources and quotes are shown in their original language (French).",
        "badges": {"Géorisques": "Géorisques · official", OFFICIEL_LOCAL: "local official", PRESSE: "press",
                   RESEAU_SOCIAL: "social media", AUTRE_SITE: "other site"},
        "a_verifier": "unofficial, to be checked",
        "continuer_degats": "Next: my damage →",
        "continuer_lettre": "Next: my letter →",
        "retour": "← Back",
        "photos_demo_info": "📸 Demo: 3 royalty-free sample photos (floods in the United States). You can also upload your own.",
        "credits_photos": "Credits: B137 (CC0), King Prince (CC BY 2.0), Infrogmation (CC BY 2.5), via Wikimedia Commons. [Details]({url}/blob/main/exemples/CREDITS.md)",
        "utiliser_mes_photos": "Use my own photos",
        "ajouter_photos": "Add photos of your damage (6 maximum)",
        "aide_photos": "JPG, PNG or WEBP. Photos left for this session: {n}.",
        "description": "Describe your damage in your own words (optional, French preferred)",
        "description_exemple": "E.g.: the water rose 50 cm in the living room, the boiler no longer works…",
        "analyser_photos": "🔍 Analyse my {n} photo(s)",
        "analyse_photos_en_cours": "The AI is looking at your photos one by one (≈ 20 s per photo)…",
        "trop_de_photos": "6 photos maximum at a time.",
        "inventaire": "Damage inventory",
        "inventaire_aide": "Review each line: correct it, delete it (tick the left box, then 🗑️) or add a line (bottom of the table). "
                           "Fill in the estimated value if you know it. The inventory stays in French for your insurer.",
        "photos_numeros": "Photo numbers: {liste}",
        "lignes_rejetees": "{n} line(s) suggested by the AI rejected by the code (missing field, price, invalid photo number…).",
        "inventaire_manuel": "✍️ Enter the inventory manually",
        "colonnes": {"photo": "Photo", "zone": "Room", "objet": "Item", "dommage": "Damage observed",
                     "certitude": "Certainty", "valeur": "Estimated value (€)"},
        "relu": "✅ I have reviewed the inventory",
        "relu_ok": "Inventory confirmed: {n} line(s).",
        "modifs_non_validees": "You changed the inventory: click “I have reviewed the inventory” again.",
        "relire_obligatoire": "Review the inventory and click “I have reviewed the inventory” to continue.",
        "rien_a_declarer": "Add photos, a description or an inventory line to continue.",
        "lettre_avec_arrete": "📄 The letter will cite the official decree **{ref}**, published in the Official Journal on **{jo}**.",
        "lettre_sans_arrete": "📄 No decree has been published yet: the letter reports your damage **right now**, without waiting. "
                              "Enter the type of event and its date.",
        "lettre_en_francais": "🇫🇷 Your letter is always written **in French**: it is addressed to a French insurer, under French insurance law (Code des assurances).",
        "alerte_depasse": "⚠️ The legal deadline has passed. Contact your insurer immediately and explain your situation.",
        "nom": "Full name",
        "adresse": "Address of the damaged home",
        "assureur": "Insurer",
        "adresse_assureur": "Insurer's address",
        "contrat": "Policy number",
        "type_evenement": "Type of event (in French)",
        "type_exemple": "E.g.: inondations et coulées de boue",
        "date_debut": "Date of the event (start)",
        "date_fin": "End date (optional)",
        "vide_a_completer": "Empty fields will appear as [À COMPLÉTER] (to be completed) in the letter.",
        "generer": "✍️ Generate my letter",
        "generation": "The AI drafts the body of the letter, the code checks it and inserts the facts (≈ 30 s)…",
        "apercu": "Letter preview",
        "telecharger": "⬇️ Download the letter (PDF)",
        "a_envoyer": "Send it by **registered letter with acknowledgement of receipt**, after reviewing it.",
        "checklist": "Documents to attach or prepare",
        "checklist_fr": "In French, as your insurer will expect.",
        "brouillons_refuses": "{n} AI draft(s) rejected by the code before the final version.",
        "version_simplifiee": "ℹ️ Simplified version: this letter was written from a fixed template. Review it and complete it if needed.",
        "cout": "Cost of this step: {tokens} tokens",
        "limite_analyses": "Limit reached: 3 town analyses per session (public demo). Please come back later.",
        "limite_lettres": "Limit reached: 2 letters per session (public demo). Please come back later.",
        "limite_photos": "Limit reached: 6 photos per session (public demo). You have {n} left.",
        "limite_tokens": "The demo's global AI budget is used up (spending safeguard). Thank you for your understanding.",
        "erreur_technique": "A technical problem occurred: {detail}. Please try again in a moment.",
        "comment": "🧭 How it works",
        "comment_code": "#### 🧮 Done by the code (reliable, verifiable)",
        "comment_code_liste": [
            "**Official facts**: natural disaster decrees (Géorisques API), towns (geo.api.gouv.fr)",
            "**Dates and deadlines**: safe deadline = publication in the Official Journal + 29 days (the law allows 30 days, art. L125-2 of the French Insurance Code)",
            "**Web source checks**: URL actually found, quote present word for word, site reliability level, town name",
            "**Final say on the case** A/B/C/E/D, and every piece of **advice** shown",
            "**Letter**: header, subject, dates, references inserted by the code; an AI draft is rejected if it invents a number or a date",
            "**Safeguards**: token budget, per-session limits",
        ],
        "comment_ia": "#### 🤖 Done by the AI (NVIDIA Nemotron, via Nebius)",
        "comment_ia_liste": [
            "**Classifying the situation** from decrees and news: `{radar}`",
            "**Reading the photos** and listing visible damage: `{vision}`",
            "**Drafting the body of the letter**, with placeholders filled by the code: `{lettre}`",
            "**Web search**: Tavily (2 searches per town, cached for 24 h)",
        ],
        "comment_regle": "**Golden rule**: the AI never invents a fact. It drafts and classifies; the code provides and checks the facts.",
        "session": "My session",
        "restant": "Analyses: {a}/3 · Letters: {l}/2 · Photos: {p}/6",
        "effacer": "🧹 Delete my data and start over",
        "pied": "Prototype built for the Nebius x NVIDIA hackathon · NVIDIA Nemotron · Tavily · data from Géorisques and geo.api.gouv.fr",
        "code_source": "source code",
    },
}

# Couleurs des cartes (une par cas) et des badges de source
COULEURS_CAS = {"A": "#1b7f4b", "B": "#1f5fa8", "C": "#c25e00", "E": "#b42318", "D": "#5f6b7a"}
COULEURS_BADGES = {"Géorisques": "#0b6e4f", OFFICIEL_LOCAL: "#1f5fa8", PRESSE: "#6941c6",
                   RESEAU_SOCIAL: "#c25e00", AUTRE_SITE: "#5f6b7a"}

CSS = """
<style>
.block-container {max-width: 860px; padding-top: 2rem;}
h1.titre {font-size: 2.3rem; margin: 0; letter-spacing: -0.02em;}
p.slogan {color: #52606d; font-size: 1.05rem; margin-top: .2rem;}
.etapes {display: flex; gap: .4rem; flex-wrap: wrap; margin: .3rem 0 .6rem;}
.etape {padding: .25rem .75rem; border-radius: 999px; font-size: .85rem; background: #eef1f5; color: #52606d;}
.etape.active {background: #1f5fa8; color: white; font-weight: 600;}
.etape.faite {background: #e3f1ea; color: #1b7f4b;}
.carte {border-radius: 16px; padding: 1.2rem 1.4rem; border-left: 8px solid; margin: .8rem 0 1rem; background: #f7f9fb;}
.carte .cas {font-size: .8rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em;}
.carte .libelle {font-size: 1.25rem; font-weight: 700; margin: .2rem 0 .6rem; color: #1f2933;}
.carte .compte {font-size: 5rem; font-weight: 800; line-height: 1;}
.carte .compte-texte {font-size: 1.05rem; font-weight: 600; margin-bottom: .4rem;}
.carte .conseil {font-size: 1.02rem; color: #1f2933; margin-top: .6rem;}
.badge {display: inline-block; padding: .12rem .6rem; border-radius: 999px; color: white; font-size: .72rem;
        font-weight: 600; margin: 0 .35rem .25rem 0; white-space: nowrap;}
.badge.contour {background: white !important; border: 1px solid #c3cad3; color: #52606d;}
.source {padding: .7rem .9rem; border: 1px solid #e4e7eb; border-radius: 12px; margin: .45rem 0; background: white;}
.source .texte {margin: .25rem 0; color: #1f2933;}
.source .citation {color: #52606d; font-style: italic; font-size: .9rem;}
.source a {font-size: .85rem; word-break: break-all;}
.lettre {white-space: pre-wrap; font-family: Georgia, "Times New Roman", serif; background: white; color: #1f2933;
         border: 1px solid #e4e7eb; border-radius: 12px; padding: 1.6rem; line-height: 1.55; font-size: .95rem;
         box-shadow: 0 2px 10px rgba(15, 23, 42, .06);}
.pied {color: #7b8794; font-size: .8rem; text-align: center; margin-top: 2.5rem;}
@media (max-width: 640px) {
  h1.titre {font-size: 1.8rem;}
  .carte .compte {font-size: 3.6rem;}
  .lettre {padding: 1rem; font-size: .88rem;}
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
        "inventaire_df": None, "inventaire_photos": [], "inventaire_rejetees": 0, "inventaire_valide": None,
        "resultat_lettre": None, "inventaire_lettre": None, "tokens_photos": 0,
        "compteurs": {"analyses": 0, "lettres": 0, "photos": 0},
    }
    for cle, valeur in defauts.items():
        st.session_state.setdefault(cle, valeur)


def effacer_donnees():
    """Efface tout ce qui est personnel (les compteurs de la session sont conservés)."""
    compteurs, langue = st.session_state.compteurs, st.session_state.langue
    for cle in list(st.session_state.keys()):
        del st.session_state[cle]
    st.session_state.compteurs, st.session_state.langue = compteurs, langue


def lancer_demo():
    """Bouton « Essayer la démo » : pré-remplit Martigues, les 3 photos et un sinistré fictif."""
    for cle in ("choix_commune", "editeur_inventaire"):
        st.session_state.pop(cle, None)
    for cle, valeur in DEMO.items():
        st.session_state[cle] = valeur
    st.session_state.update(etape=1, demo_photos=True, lancer_analyse=True, radar=None, inventaire_df=None,
                            inventaire_valide=None, resultat_lettre=None)


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


def conseil(cas, resultat, en_cours):
    """Conseil écrit par le code (français : celui de radar.py ; anglais : sa traduction)."""
    if st.session_state.langue == "fr":
        return resultat["conseil"]
    if cas == "A":
        c = en_cours[0][1]
        return (f"Report your damage to your insurer by registered letter with acknowledgement of receipt "
                f"before {_format(c['date_limite'])} ({c['jours_restants']} days left).")
    return {
        "B": "A decree seems to have been published (unofficial, check on legifrance.gouv.fr). The claim deadline "
             "starts on publication in the Official Journal: report your damage to your insurer now, without "
             "waiting for it to appear in Géorisques.",
        "C": "Report your damage to your insurer now, without waiting for the decree. Also report it to your town "
             "hall to support its recognition request.",
        "E": "The legal deadline has passed. Contact your insurer immediately and explain your situation.",
        "D": "No recent procedure detected. If you have damage, report it to your insurer anyway and tell your town "
             "hall, which can request recognition.",
    }[cas]


def gerer_erreur(action):
    """Exécute `action` et affiche un message clair en cas de problème. Renvoie son résultat, ou None."""
    try:
        return action()
    except LimiteTokensAtteinte:
        st.error(t("limite_tokens"))
    except Exception as erreur:  # réseau, API indisponible, réponse illisible...
        st.error(t("erreur_technique", detail=str(erreur)[:200]))
    return None


def df_depuis_inventaire(inventaire):
    colonnes = ["photo", "zone", "objet", "dommage", "certitude", "valeur"]
    df = pd.DataFrame([{**{c: l.get(c) for c in colonnes[:-1]}, "valeur": None} for l in inventaire], columns=colonnes)
    return df.astype({"photo": "Int64", "valeur": "float64"})


def _texte(valeur):
    return "" if valeur is None or (not isinstance(valeur, str) and pd.isna(valeur)) else str(valeur).strip()


def df_vers_inventaire(df):
    """Convertit le tableau modifié par le sinistré en lignes d'inventaire pour la lettre."""
    lignes = []
    for _, r in df.iterrows():
        objet = _texte(r.get("objet"))
        if not objet:
            continue  # ligne vide : ignorée
        valeur = r.get("valeur")
        lignes.append({
            "zone": _texte(r.get("zone")) or A_COMPLETER,
            "objet": objet,
            "dommage": _texte(r.get("dommage")) or A_COMPLETER,
            # Une ligne ajoutée par le sinistré lui-même est considérée comme certaine
            "certitude": r.get("certitude") if r.get("certitude") in (CERTAIN, PROBABLE) else CERTAIN,
            "photo": int(r["photo"]) if _texte(r.get("photo")) else None,
            "valeur_estimee": f"{round(float(valeur)):,} €".replace(",", " ") if _texte(valeur) else A_COMPLETER,
        })
    return lignes


# ---------------------------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------------------------
def afficher_entete():
    col_titre, col_langue = st.columns([5, 1.3])
    with col_titre:
        st.markdown('<h1 class="titre">🌊 30 Days</h1>', unsafe_allow_html=True)
        st.markdown(f'<p class="slogan">{html.escape(t("slogan"))}</p>', unsafe_allow_html=True)
    with col_langue:
        st.radio("Langue / Language", ["fr", "en"], key="langue", horizontal=True, label_visibility="collapsed",
                 format_func=lambda l: {"fr": "🇫🇷 FR", "en": "🇬🇧 EN"}[l])
    st.button(t("demo"), on_click=lancer_demo, help=t("demo_aide"), type="secondary", width="stretch")
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


def afficher_progression():
    etape = st.session_state.etape
    noms = t("etapes")
    pastilles = "".join(
        f'<span class="etape {"active" if i == etape else "faite" if i < etape else ""}">{i}. {html.escape(nom)}</span>'
        for i, nom in enumerate(noms, start=1)
    )
    st.markdown(f'<div class="etapes">{pastilles}</div>', unsafe_allow_html=True)
    st.progress(etape / 3, text=t("etape_n", n=etape, nom=noms[etape - 1]))


def afficher_source(affirmation):
    niveau = affirmation["niveau"]
    badges = f'<span class="badge" style="background:{COULEURS_BADGES.get(niveau, "#5f6b7a")}">{html.escape(t("badges").get(niveau, niveau))}</span>'
    if affirmation["statut"] == NON_OFFICIEL:
        badges += f'<span class="badge contour">{html.escape(t("a_verifier"))}</span>'
    citation = (f'<div class="citation">« {html.escape(affirmation["citation"])} »</div>'
                if affirmation.get("citation") else "")
    lien = affirmation["source"]
    nom_lien = urlparse(lien).netloc.removeprefix("www.") or lien
    st.markdown(
        f'<div class="source">{badges}<div class="texte">{html.escape(affirmation["texte"])}</div>{citation}'
        f'<a href="{html.escape(lien)}" target="_blank" rel="noopener">↗ {html.escape(nom_lien)}</a></div>',
        unsafe_allow_html=True,
    )


def afficher_radar():
    donnees, commune = st.session_state.radar, st.session_state.commune
    resultat = donnees["resultat"]
    cas = resultat["cas"]
    en_cours, depasses = trier_arretes(donnees["arretes"])
    couleur = COULEURS_CAS[cas]

    detail = ""
    if cas == "A" and en_cours:
        c = en_cours[0][1]
        unite = t("jour_restant") if c["jours_restants"] <= 1 else t("jours_restants")
        detail = (f'<div class="compte" style="color:{couleur}">{c["jours_restants"]}</div>'
                  f'<div class="compte-texte">{unite}</div><div>{t("avant_le", date=_format(c["date_limite"]))}</div>')
    elif cas == "E" and depasses:
        detail = f'<div>{t("depasse_le", date=_format(depasses[0][1]["date_limite"]))}</div>'
    st.markdown(
        f'<div class="carte" style="border-color:{couleur}; background:{couleur}12">'
        f'<div class="cas" style="color:{couleur}">{html.escape(commune["nom"])} ({commune["departement"]}) · {t("cas", cas=cas)}</div>'
        f'<div class="libelle">{html.escape(t("libelles")[cas])}</div>{detail}'
        f'<div class="conseil">👉 <b>{html.escape(conseil(cas, resultat, en_cours))}</b></div></div>',
        unsafe_allow_html=True,
    )

    if cas != "E" and depasses:
        brut, c = depasses[0]
        st.info(t("info_depasse", type=c["type"], jo=_format(c["publication_jo"]), limite=_format(c["date_limite"])))

    st.markdown(f"**{t('explication_ia')}** : {resultat['explication']}")
    with st.expander(t("verifications")):
        if resultat["corrections"]:
            st.markdown(t("corrections"))
            st.markdown("\n".join(f"- {c}" for c in resultat["corrections"]))
        else:
            st.markdown(t("aucune_correction"))
        if resultat["rejetees"]:
            st.markdown(t("rejetees"))
            st.markdown("\n".join(f"- {r['raison']} ({r['source'] or '—'})" for r in resultat["rejetees"]))
        st.caption(t("cout", tokens=resultat["tokens"]["total_tokens"]))

    st.markdown(f"#### {t('sources')}")
    if t("sources_fr"):
        st.caption(t("sources_fr"))
    for affirmation in resultat["affirmations"]:
        afficher_source(affirmation)


# ---------------------------------------------------------------------------------------------
# Les 3 étapes
# ---------------------------------------------------------------------------------------------
def etape_commune():
    col_nom, col_dep = st.columns([3, 1])
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
    clic = st.button(t("analyser"), type="primary", disabled=choix is None, width="stretch")
    if (clic or demande_demo) and choix:
        if st.session_state.compteurs["analyses"] >= LIMITES["analyses"]:
            st.error(t("limite_analyses"))
        else:
            with st.spinner(t("analyse_en_cours")):
                donnees = gerer_erreur(lambda: radar_commune(choix["code"], choix["nom"], choix["codeDepartement"]))
            if donnees:
                st.session_state.compteurs["analyses"] += 1
                st.session_state.commune = {"nom": choix["nom"], "code": choix["code"],
                                            "departement": choix["codeDepartement"]}
                st.session_state.radar = donnees
                st.session_state.resultat_lettre = None

    if st.session_state.radar:
        afficher_radar()
        if st.button(t("continuer_degats"), type="primary", width="stretch"):
            st.session_state.etape = 2
            st.rerun()


def etape_degats():
    compteurs = st.session_state.compteurs
    restantes = LIMITES["photos"] - compteurs["photos"]
    fichiers = []
    if st.session_state.demo_photos:
        st.info(t("photos_demo_info"))
        colonnes = st.columns(len(PHOTOS_DEMO))
        for numero, (colonne, chemin) in enumerate(zip(colonnes, PHOTOS_DEMO), start=1):
            colonne.image(str(chemin), caption=f"{numero}. {chemin.name}", width="stretch")
        st.caption(t("credits_photos", url=URL_DEPOT))
        if st.button(t("utiliser_mes_photos")):
            st.session_state.demo_photos = False
            st.rerun()
    else:
        fichiers = st.file_uploader(t("ajouter_photos"), type=["jpg", "jpeg", "png", "webp"],
                                    accept_multiple_files=True, help=t("aide_photos", n=restantes)) or []

    st.text_area(t("description"), key="description", placeholder=t("description_exemple"))

    nombre = len(PHOTOS_DEMO) if st.session_state.demo_photos else len(fichiers)
    if nombre:
        if st.button(t("analyser_photos", n=nombre), type="primary", width="stretch"):
            if nombre > LIMITES["photos"]:
                st.error(t("trop_de_photos"))
            elif not st.session_state.demo_photos and nombre > restantes:
                st.error(t("limite_photos", n=restantes))
            else:
                with st.spinner(t("analyse_photos_en_cours")):
                    analyse = gerer_erreur(inventaire_demo if st.session_state.demo_photos
                                           else lambda: analyser_photos(fichiers))
                if analyse:
                    if not st.session_state.demo_photos:  # les photos de démo, déjà analysées, ne comptent pas
                        compteurs["photos"] += nombre
                    st.session_state.pop("editeur_inventaire", None)
                    st.session_state.update(
                        inventaire_df=df_depuis_inventaire(analyse["inventaire"]),
                        inventaire_photos=analyse["photos"], inventaire_rejetees=len(analyse["rejetees"]),
                        inventaire_valide=None, tokens_photos=analyse["tokens"]["total_tokens"],
                    )

    if st.session_state.inventaire_df is None:
        if st.button(t("inventaire_manuel")):
            st.session_state.inventaire_df = df_depuis_inventaire([])
            st.rerun()
        inventaire_courant = []
    else:
        st.markdown(f"#### {t('inventaire')}")
        st.caption(t("inventaire_aide"))
        noms = t("colonnes")
        edite = st.data_editor(
            st.session_state.inventaire_df, key="editeur_inventaire", num_rows="dynamic", hide_index=True,
            width="stretch",
            column_config={
                "photo": st.column_config.NumberColumn(noms["photo"], min_value=1, step=1, width="small"),
                "zone": st.column_config.TextColumn(noms["zone"]),
                "objet": st.column_config.TextColumn(noms["objet"], required=True),
                "dommage": st.column_config.TextColumn(noms["dommage"], width="large"),
                "certitude": st.column_config.SelectboxColumn(noms["certitude"], options=[CERTAIN, PROBABLE]),
                "valeur": st.column_config.NumberColumn(noms["valeur"], min_value=0, step=10, format="%d €"),
            },
        )
        if st.session_state.inventaire_photos:
            st.caption(t("photos_numeros", liste=" · ".join(
                f"{i}. {nom}" for i, nom in enumerate(st.session_state.inventaire_photos, start=1))))
        if st.session_state.inventaire_rejetees:
            st.caption(t("lignes_rejetees", n=st.session_state.inventaire_rejetees))
        if st.session_state.tokens_photos:
            st.caption(t("cout", tokens=st.session_state.tokens_photos))
        inventaire_courant = df_vers_inventaire(edite)
        if st.button(t("relu"), type="primary", width="stretch"):
            st.session_state.inventaire_valide = inventaire_courant

    valide = st.session_state.inventaire_valide
    inventaire_relu = valide is not None and valide == inventaire_courant
    if valide is not None and not inventaire_relu:
        st.warning(t("modifs_non_validees"))
    elif inventaire_relu:
        st.success(t("relu_ok", n=len(valide)))

    pret = inventaire_relu or (not inventaire_courant and st.session_state.get("description", "").strip())
    if not pret:
        st.caption(t("relire_obligatoire") if inventaire_courant else t("rien_a_declarer"))

    col_retour, col_suite = st.columns(2)
    if col_retour.button(t("retour"), width="stretch"):
        st.session_state.etape = 1
        st.rerun()
    if col_suite.button(t("continuer_lettre"), type="primary", disabled=not pret, width="stretch"):
        st.session_state.inventaire_lettre = valide if inventaire_relu else []
        st.session_state.etape = 3
        st.rerun()


def etape_lettre():
    donnees, commune = st.session_state.radar, st.session_state.commune
    cas = donnees["resultat"]["cas"]
    en_cours, depasses = trier_arretes(donnees["arretes"])
    # Cas A : l'arrêté au délai en cours ; cas E : le dernier arrêté expiré ; sinon pas encore d'arrêté
    arrete = en_cours[0] if cas == "A" and en_cours else depasses[0] if cas == "E" and depasses else None

    if t("lettre_en_francais"):
        st.info(t("lettre_en_francais"))
    if arrete:
        st.info(t("lettre_avec_arrete", ref=arrete[0].get("code_national_catnat", "?"),
                  jo=_format(arrete[1]["publication_jo"])))
    else:
        st.info(t("lettre_sans_arrete"))
    if cas == "E":
        st.warning(t("alerte_depasse"))

    with st.form("formulaire_lettre"):
        st.text_input(t("nom"), key="f_nom")
        st.text_input(t("adresse"), key="f_adresse")
        col_a, col_b = st.columns(2)
        col_a.text_input(t("assureur"), key="f_assureur")
        col_b.text_input(t("contrat"), key="f_contrat")
        st.text_input(t("adresse_assureur"), key="f_adresse_assureur")
        if not arrete:
            st.text_input(t("type_evenement"), key="f_type", placeholder=t("type_exemple"))
            col_c, col_d = st.columns(2)
            col_c.date_input(t("date_debut"), key="f_debut", value=st.session_state.get("f_debut"), format="DD/MM/YYYY")
            col_d.date_input(t("date_fin"), key="f_fin", value=st.session_state.get("f_fin"), format="DD/MM/YYYY")
        st.caption(t("vide_a_completer"))
        envoyer = st.form_submit_button(t("generer"), type="primary", width="stretch")

    if envoyer:
        if st.session_state.compteurs["lettres"] >= LIMITES["lettres"]:
            st.error(t("limite_lettres"))
        else:
            sinistre = {
                "nom": st.session_state.f_nom, "adresse": st.session_state.f_adresse,
                "assureur": st.session_state.f_assureur, "adresse_assureur": st.session_state.f_adresse_assureur,
                "numero_contrat": st.session_state.f_contrat,
                "description_degats": st.session_state.get("description", ""),
                "commune": commune["nom"], "type_evenement": st.session_state.get("f_type"),
                "date_debut": st.session_state.get("f_debut"), "date_fin": st.session_state.get("f_fin"),
            }
            inventaire = st.session_state.inventaire_lettre or None
            with st.spinner(t("generation")):
                resultat = gerer_erreur(lambda: generer_lettre(arrete[0] if arrete else None, sinistre, inventaire))
            if resultat:
                st.session_state.compteurs["lettres"] += 1
                resultat["pdf"] = lettre_en_pdf(resultat["lettre"], inventaire)
                resultat["inventaire"] = inventaire
                st.session_state.resultat_lettre = resultat

    resultat = st.session_state.resultat_lettre
    if resultat:
        st.markdown(f"#### {t('apercu')}")
        corps = resultat["lettre"].split(SEPARATEUR_ANNEXE)[0].strip()
        st.markdown(f'<div class="lettre">{html.escape(corps)}</div>', unsafe_allow_html=True)
        if resultat["inventaire"]:
            st.markdown(f"**{TITRE_ANNEXE}**")
            st.dataframe(pd.DataFrame(resultat["inventaire"]).rename(columns={
                "zone": "Pièce", "objet": "Objet", "dommage": "Dommage constaté", "certitude": "Certitude",
                "photo": "Photo", "valeur_estimee": "Valeur estimée"}), hide_index=True, width="stretch")
            st.caption(NOTE_ANNEXE)
        if resultat["secours"]:  # l'IA a échoué : lettre du modèle fixe, signalée discrètement
            st.caption(t("version_simplifiee"))
        elif resultat["rejets"]:
            st.caption(t("brouillons_refuses", n=len(resultat["rejets"])))
        st.caption(t("cout", tokens=resultat["tokens"]["total_tokens"]))

        st.download_button(t("telecharger"), data=resultat["pdf"], file_name="declaration_sinistre_catnat.pdf",
                           mime="application/pdf", type="primary", width="stretch")
        st.markdown(t("a_envoyer"))

        st.markdown(f"#### {t('checklist')}")
        if t("checklist_fr"):
            st.caption(t("checklist_fr"))
        for numero, piece in enumerate(resultat["checklist"]):
            st.checkbox(piece, key=f"piece_{numero}")

    if st.button(t("retour"), width="stretch"):
        st.session_state.etape = 2
        st.rerun()


# ---------------------------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------------------------
st.set_page_config(page_title="30 Days", page_icon="🌊", layout="centered")
initialiser_session()
st.markdown(CSS, unsafe_allow_html=True)

afficher_entete()
st.caption(t("confidentialite"))
afficher_progression()

# Sans commune analysée, on ne peut pas aller plus loin que l'étape 1
if st.session_state.etape > 1 and not st.session_state.radar:
    st.session_state.etape = 1
{1: etape_commune, 2: etape_degats, 3: etape_lettre}[st.session_state.etape]()

with st.sidebar:
    st.markdown(f"### {t('session')}")
    c = st.session_state.compteurs
    st.caption(t("restant", a=c["analyses"], l=c["lettres"], p=c["photos"]))
    st.button(t("effacer"), on_click=effacer_donnees, width="stretch")
    st.caption(t("avertissement"))

st.markdown(f'<div class="pied">{html.escape(t("avertissement"))}<br>{html.escape(t("pied"))} · '
            f'<a href="{URL_DEPOT}" target="_blank" rel="noopener">{t("code_source")}</a></div>',
            unsafe_allow_html=True)

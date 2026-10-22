"""Appel à Nemotron via Nebius Token Factory, avec un compteur de tokens anti-dépense."""

import base64
import io
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image, ImageOps

load_dotenv()

MODELE_PAR_DEFAUT = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
FICHIER_USAGE = Path(__file__).parent / "usage.json"
TAILLE_MAX_IMAGE = 1600  # en pixels, pour le plus grand côté : moins de pixels = moins de tokens


def preparer_image(chemin, taille_max=TAILLE_MAX_IMAGE):
    """Réduit une photo à `taille_max` pixels maximum et la renvoie au format attendu par l'API.

    `chemin` : chemin d'un fichier, ou fichier déjà ouvert en mémoire (photo envoyée depuis l'interface).
    """
    if hasattr(chemin, "seek"):
        chemin.seek(0)  # un fichier en mémoire peut être relu plusieurs fois (nouvel essai)
    with Image.open(chemin) as image:
        image = ImageOps.exif_transpose(image)  # remet droites les photos de téléphone tournées
        image = image.convert("RGB")
        image.thumbnail((taille_max, taille_max))  # garde les proportions, ne fait jamais grossir
        tampon = io.BytesIO()
        image.save(tampon, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(tampon.getvalue()).decode()


class LimiteTokensAtteinte(Exception):
    """Le garde-fou refuse l'appel : la limite MAX_TOKENS_TOTAL est atteinte (ou absente)."""


def _lire_usage():
    if FICHIER_USAGE.exists():
        return json.loads(FICHIER_USAGE.read_text())
    return {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "nombre_appels": 0}


def appeler_nemotron(messages, modele=MODELE_PAR_DEFAUT, images=None, **options):
    """Envoie des messages à un modèle Nemotron et renvoie (texte de la réponse, tokens de cet appel).

    `messages` est soit une simple question (texte), soit une liste de messages au format OpenAI.
    `images` : liste de chemins de photos, jointes au dernier message (modèle « VL » nécessaire).
    Les tokens sont additionnés dans usage.json ; au-delà de MAX_TOKENS_TOTAL, l'appel est refusé.
    """
    limite = os.getenv("MAX_TOKENS_TOTAL")
    if not limite:
        raise LimiteTokensAtteinte("MAX_TOKENS_TOTAL est absent de .env : appel refusé par sécurité.")
    usage = _lire_usage()
    if usage["total_tokens"] >= int(limite):
        raise LimiteTokensAtteinte(
            f"Limite atteinte : {usage['total_tokens']} tokens déjà utilisés sur {limite} autorisés."
        )

    api_key = os.getenv("NEBIUS_API_KEY")
    if not api_key:
        raise RuntimeError("NEBIUS_API_KEY est vide dans .env.")
    client = OpenAI(base_url="https://api.tokenfactory.nebius.com/v1", api_key=api_key)

    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    if images:
        # Le dernier message devient « texte + photos », au format compatible OpenAI
        dernier = messages[-1]
        contenu = [{"type": "text", "text": dernier["content"]}] + [
            {"type": "image_url", "image_url": {"url": preparer_image(chemin)}} for chemin in images
        ]
        messages = messages[:-1] + [{**dernier, "content": contenu}]
    reponse =client.chat.completions.create(model=modele, messages=messages, **options)

    # Ajouter les tokens de cet appel au total enregistré
    tokens = {
        "prompt_tokens": reponse.usage.prompt_tokens,
        "completion_tokens": reponse.usage.completion_tokens,
        "total_tokens": reponse.usage.total_tokens,
    }
    for cle, valeur in tokens.items():
        usage[cle] += valeur
    usage["nombre_appels"] += 1
    FICHIER_USAGE.write_text(json.dumps(usage, indent=2))

    texte = reponse.choices[0].message.content or ""
    # Certains modèles « qui réfléchissent » mettent leur raisonnement entre <think> et </think>
    texte = re.sub(r"<think>.*?</think>", "", texte, flags=re.DOTALL).strip()
    return texte, tokens

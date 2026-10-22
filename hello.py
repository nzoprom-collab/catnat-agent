"""Premier test de Nebius Token Factory : liste les modèles Nemotron et pose une question."""

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

# 1. Lire la clé API depuis le fichier .env (sans jamais l'afficher)
load_dotenv()
api_key = os.getenv("NEBIUS_API_KEY")
if not api_key:
    sys.exit("Erreur : NEBIUS_API_KEY est vide. Ouvre le fichier .env et colle ta clé après le signe =.")

# 2. Créer le client : c'est la librairie OpenAI, mais pointée vers les serveurs Nebius
client = OpenAI(
    base_url="https://api.tokenfactory.nebius.com/v1",
    api_key=api_key,
)

# 3. Lister les modèles dont l'identifiant contient "nemotron"
nemotron_models = sorted(m.id for m in client.models.list() if "nemotron" in m.id.lower())
print("Modèles Nemotron disponibles :")
for model_id in nemotron_models:
    print(f"  - {model_id}")

# 4. Choisir le modèle Nemotron Nano (le premier dont le nom contient aussi "nano")
nano_models = [m for m in nemotron_models if "nano" in m.lower()]
if not nano_models:
    sys.exit("Aucun modèle Nemotron Nano trouvé dans la liste ci-dessus.")
model = nano_models[0]

# 5. Envoyer la question et afficher la réponse
response = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "Bonjour, présente-toi en une phrase"}],
)
print(f"\nModèle utilisé : {model}")
print(f"Réponse : {response.choices[0].message.content}")

# 6. Afficher le nombre de tokens consommés (c'est ce qui est facturé)
usage = response.usage
print(
    f"\nTokens utilisés : {usage.prompt_tokens} (question) "
    f"+ {usage.completion_tokens} (réponse) = {usage.total_tokens} au total"
)

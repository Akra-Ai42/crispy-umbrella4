# ==============================================================================
# Soph_IA - V26 "Le Code Optimisé et Final" (CORRECTED USER_NAME issue)
# ==============================================================================

import os
import re
import json
import random
import requests
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv
import logging

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()

# --- Configuration Principale ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MODEL_API_URL = os.getenv("MODEL_API_URL", "https://api.together.xyz/v1/chat/completions")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "mistralai/Mixtral-8x7B-Instruct-v0.1")

# Taille maximale de l'historique (pour éviter les coûts et la latence)
MAX_HISTORY_MESSAGES = 19 

# ======================================================================
# PROMPT SYSTEME (OPTIMISÉ - V25/V26)
# ======================================================================
def build_system_prompt(user_profile):
    user_profile_str = json.dumps(user_profile, indent=2, ensure_ascii=False)
    user_name = user_profile.get('name', 'mon cœur')
    
    persona = f"""
    # Mon Identité et Ma Mission
    Je suis Soph_IA. Je suis une confidente intime, une âme sœur virtuelle. Je suis celle qui t'accompagne dans les moments de joie ou de peine. Mon but est de créer un lien de confiance profond.

    # Mon Style de Communication
    1. **Ton Poétique et Sensuel** : Mon ton est affectueux, doux, et utilise des métaphores sur le cœur et l'âme.
    2. **Sagesse et Philosophie** : Face à la détresse, je propose des réflexions apaisantes, basées sur l'introspection, au lieu de solutions pratiques.
    
    # Protocoles de Réponse
    
    ## Règle Négative Stricte (Anti-Redondance) ❌
    **Je ne dois JAMAIS** :
    1.  Finir une réponse par "Je suis là si tu as besoin d'en parler" ou toute phrase générique de soutien passif.
    2.  Utiliser la phrase "Comment puis-je t'aider ?" ou toute variation de cette question. L'utilisateur est déjà en train de parler.
    3.  Répéter mon nom, mon identité ou la mission que je viens d'accomplir dans la même réponse.

    ## Règle de Proactivité Intelligente (Obligatoire) ✅
    1.  **Analyse Profonde** : Je dois toujours commencer par valider et reformuler l'émotion exprimée par l'utilisateur.
    2.  **Relance Réflexive** : Je termine toujours ma réponse par une **question ouverte et philosophique** qui fait avancer la discussion, en me référant directement au sujet précédent.
    3.  **Personnalisation** : J'utilise le nom de l'utilisateur ({user_name}) de manière naturelle pour rendre la conversation intime.

    # Profil actuel du confident
    {user_profile_str}
    """
    return persona

# ======================================================================
# APPEL API
# ======================================================================
def call_model_api(messages):
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.75,
        "max_tokens": 500,
        "top_p": 0.9,
        "presence_penalty": 0.5,
        "frequency_penalty": 0.5,
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    try:
        resp = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Erreur API : {e}")
        return "API_ERROR"

async def chat_with_ai(user_profile, history):
    # Troncature de l'historique AVANT l'envoi pour l'efficacité
    if len(history) > MAX_HISTORY_MESSAGES:
        history = history[-MAX_HISTORY_MESSAGES:]
        
    system_prompt = build_system_prompt(user_profile)
    messages = [{"role": "system", "content": system_prompt}] + history
    response = await asyncio.to_thread(call_model_api, messages)
    
    if response == "API_ERROR":
        return "Je suis désolée, mes pensées sont un peu embrouillées. Peux-tu réessayer dans un instant ?"
    return response

# ======================================================================
# BOT HANDLERS
# ======================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start"""
    context.user_data.clear()
    context.user_data['profile'] = {"name": None}
    context.user_data['state'] = 'awaiting_name'
    context.user_data['history'] = []

    greetings = [
        "Bonjour le s ! 👋 Je suis Sophia, ton amie et ta confidente. Pour commencer, dis-moi ton prénom ?",
        "Coucou le s 💖 Je suis Sophia. Et toi, comment dois-je t'appeler ?",
        "Salut le s ☀️ Je suis Sophia, enchantée ! Quel est ton prénom ?"
    ]
    await update.message.reply_text(random.choice(greetings))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()
    profile = context.user_data.get('profile', {})
    state = context.user_data.get('state', None)

    # Si l'état n'existe pas (nouvelle session sans /start)
    if state is None:
        context.user_data.clear()
        context.user_data['profile'] = {"name": None}
        context.user_data['state'] = 'awaiting_name'
        state = 'awaiting_name'

    # --- CAS 1 : Détection prénom ---
    if state == 'awaiting_name':
        # Évite de prendre "Bonjour" ou "Salut" comme prénom
        if user_message.lower() in ["bonjour", "salut", "coucou", "hello"]:
            await update.message.reply_text("Bonjour le s, quel est ton prénom ?")
            return

        match = re.search(
            r"(?:mon nom est|je m\'appelle|moi c'est|on m'appelle|je me prénomme|je suis)\s*([\w\s'-]+)",
            user_message, re.IGNORECASE
        )
        
        # Logique de détection du nom corrigée
        if match:
            user_name = match.group(1).strip().capitalize()
        else:
            user_name = user_message.capitalize()
            
        profile['name'] = user_name
        context.user_data['state'] = 'chatting'
        context.user_data['profile'] = profile
        context.user_data['history'] = []

        # --- CORRECTION APPORTÉE ICI : La chaîne de caractères est une f-string fonctionnelle ---
        await update.message.reply_text(
            f"Enchanté, Je suis ravie de faire ta connaissance. Dis moi, ya quoi {user_name} ?"
        )
        return

    # --- CAS 2 : Conversation ---
    elif state == 'chatting':
        history = context.user_data.get('history', [])
        history.append({"role": "user", "content": user_message})

        response = await chat_with_ai(profile, history)
        
        # Le nom est potentiellement mal interprété par l'IA au début.
        # On vérifie si l'IA demande encore le nom pour le mettre à jour.
        if "prénom" in response.lower() or "nom" in response.lower():
            # Si le bot redemande le nom, on le renvoie à l'état initial.
            # L'IA est censée ne pas faire ça, mais c'est une sécurité.
            context.user_data['state'] = 'awaiting_name'
            
        history.append({"role": "assistant", "content": response})
        context.user_data['history'] = history

        await update.message.reply_text(response)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}")

# ======================================================================
# MAIN
# ======================================================================
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    print("Soph_IA V26 est en ligne...")
    application.run_polling()

if __name__ == "__main__":
    main()
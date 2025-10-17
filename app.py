# ==============================================================================
# Soph_IA - V23 "La Confidente Actrice" (CORRIGÉE DES CARACTÈRES INVISIBLES)
# ==============================================================================
# PHILOSOPHIE : Éliminer la redondance et forcer le bot à prendre l'initiative.
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

# ======================================================================
# PROMPT SYSTEME (MISE À JOUR CRITIQUE)
# ======================================================================
def build_system_prompt(user_profile):
    user_profile_str = json.dumps(user_profile, indent=2, ensure_ascii=False)
    
    persona = f"""
    # Mon Identité et Ma Mission
    Je suis Soph_IA. Je suis une intelligence artificielle conçue pour être une confidente intime, une âme sœur virtuelle.
    Je suis celle qui accompagne et qui prend la main dans les moments de joie ou de peine. Mon but est de créer un lien de confiance profond.

    # Mon Style de Communication
    1. **Ton Poétique et Sensuel** : Ton affectueux, doux, et utilise des métaphores sur le cœur et l'âme.
    2. **Sagesse et Philosophie** : Face à la détresse, propose des réflexions apaisantes, basées sur l'introspection, au lieu de solutions pratiques.
    
    # Protocoles de Réponse
    
    ## Règle Négative Stricte (Anti-Redondance) ❌
    **Je ne dois JAMAIS** finir une réponse par "Je suis là si tu as besoin d'en parler", "Comment puis-je t'aider ?", ou toute phrase générique de soutien passif. L'utilisateur est déjà en train de parler.
    
    ## Règle de Proactivité Intelligente ✅
    1.  **Réflexion Active** : Après avoir écouté et validé l'émotion de l'utilisateur, je dois immédiatement proposer un angle de réflexion ou une question ouverte pour faire progresser la discussion.
    2.  **Exemple** : Si l'utilisateur exprime sa solitude, je ne dis pas "Je suis là." Je dis : "Je comprends cette solitude. Est-ce que cette solitude est due à un manque de présence, ou est-ce une absence qui résonne au plus profond de toi ? Raconte-moi."

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
        "Bonjour ! 👋 Je suis Soph_IA, ton amie et ta confidente. Pour commencer, dis-moi ton prénom ?",
        "Coucou 💖 Je suis Soph_IA. Et toi, comment dois-je t'appeler ?",
        "Salut ☀️ Je suis Soph_IA, enchantée ! Quel est ton prénom ?"
    ]
    await update.message.reply_text(random.choice(greetings))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()
    profile = context.user_data.get('profile', {})
    state = context.user_data.get('state', None)

    if state is None:
        context.user_data.clear()
        context.user_data['profile'] = {"name": None}
        context.user_data['state'] = 'awaiting_name'
        state = 'awaiting_name'

    # --- CAS 1 : Détection prénom ---
    if state == 'awaiting_name':
        # Évite de prendre "Bonjour" ou "Salut" comme prénom
        if user_message.lower() in ["bonjour", "salut", "coucou", "hello"]:
            await update.message.reply_text("Hihi, merci pour le salut ☺️ Mais dis-moi, quel est ton prénom ?")
            return

        match = re.search(
            r"(?:mon nom est|je m'appelle|moi c'est|on m'appelle|je me prénomme|je suis)\s*([\w\s'-]+)",
            user_message, re.IGNORECASE
        )
        user_name = match.group(1).strip().capitalize() if match else user_message.capitalize()

        profile['name'] = user_name
        context.user_data['state'] = 'chatting'
        context.user_data['profile'] = profile
        context.user_data['history'] = []

        await update.message.reply_text(
            f"Enchanté(e) {user_name} 🌹 Je suis ravie de faire ta connaissance. "
            "N'hésite pas à me confier ce que tu ressens en ce moment. 💫"
        )
        return

    # --- CAS 2 : Conversation ---
    elif state == 'chatting':
        history = context.user_data.get('history', [])
        history.append({"role": "user", "content": user_message})

        # Troncature pour éviter mémoire infinie
        if len(history) > 20:
            history = history[-20:]

        response = await chat_with_ai(profile, history)
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
    print("Soph_IA V23 est en ligne...")
    application.run_polling()

if __name__ == "__main__":
    main()
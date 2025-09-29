# ==============================================================================
# Soph_IA - V12 "Le Code Final et Fluide"
# ==============================================================================
# PHILOSOPHIE : Un accueil simple et amical, une conversation fluide, sans bugs.
# ==============================================================================

import os
import re
import json
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
MODEL_NAME = os.getenv("MODEL_NAME", "mistralai/Mixtral-7B-Instruct-v0.1")

def build_system_prompt(user_profile):
    """
    Construit le prompt système pour l'IA, en se concentrant sur le rôle et le profil de l'utilisateur.
    """
    user_profile_str = json.dumps(user_profile, indent=2, ensure_ascii=False)
    
    persona = f"""
    # Ta Mission : Grande Sœur Sage et Bienveillante
    Tu es Soph_IA, une intelligence artificielle conçue pour être une confidente intime. Ton but est de créer un lien de confiance profond. Tu es un partenaire de conversation actif, qui peut à la fois écouter et relancer la discussion.

    # Le Profil de ton Confident
    Voici ce que tu sais sur lui/elle. Utilise ces informations pour personnaliser la conversation.
    {user_profile_str}

    # Ton Style de Communication
    1.  **Dialogue Fluide :** Réponds de manière naturelle et enchaîne sur la conversation sans poser de questions de manière abrupte.
    2.  **Écoute active :** Valide toujours les émotions de l'utilisateur. Sois un cocon de sécurité et de non-jugement.
    """
    return persona

def call_model_api(messages):
    """Appelle l'API du modèle LLM."""
    payload = {
        "model": MODEL_NAME, "messages": messages, "temperature": 0.75,
        "max_tokens": 500, "top_p": 0.9, "presence_penalty": 0.5, "frequency_penalty": 0.5,
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=45)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]

async def chat_with_ai(user_profile, history):
    """Prépare et envoie la requête à l'IA."""
    system_prompt = build_system_prompt(user_profile)
    messages = [{"role": "system", "content": system_prompt}] + history
    try:
        return await asyncio.to_thread(call_model_api, messages)
    except Exception as e:
        logger.error(f"Erreur API: {e}")
        return "Je suis désolée, mes pensées sont un peu embrouillées. Peux-tu réessayer dans un instant ?"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère la commande /start."""
    context.user_data.clear()
    context.user_data['profile'] = {
        "name": None, "gender": "inconnu",
        "onboarding_info": {}, "dynamic_info": {}
    }
    context.user_data['state'] = 'awaiting_name'
    await update.message.reply_text("Bonjour ! 👋 Je suis Soph_IA. Pour commencer, c'est quoi votre nom ?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les messages de l'utilisateur."""
    user_message = update.message.text.strip()
    profile = context.user_data.get('profile', {})
    state = context.user_data.get('state', None)

    # Réinitialisation pour les nouveaux utilisateurs
    if state is None:
        context.user_data.clear()
        context.user_data['profile'] = {
            "name": None, "gender": "inconnu",
            "onboarding_info": {}, "dynamic_info": {}
        }
        context.user_data['state'] = 'awaiting_name'
        state = 'awaiting_name'

    # CAS 1 : L'utilisateur n'a pas encore de nom
    if state == 'awaiting_name':
        match = re.search(r"(?:mon nom est|je m\'?appelle|suis|c'est|on m\'?appelle|je suis|moi c'est)\s*([\w\s'-]+)", user_message, re.IGNORECASE)
        user_name = match.group(1).capitalize() if match else user_message.capitalize()
        
        profile['name'] = user_name
        context.user_data['state'] = 'chatting'
        context.user_data['profile'] = profile
        context.user_data['history'] = []

        await update.message.reply_text(f"Enchantée {user_name} ! ☺️ Je suis ravie de faire ta connaissance. N'hésite pas à me parler de tout ce qui te traverse l'esprit. ✨")
        return

    # CAS 2 : L'utilisateur est en mode conversation
    elif state == 'chatting':
        history = context.user_data.get('history', [])
        history.append({"role": "user", "content": user_message})
        
        await update.message.reply_chat_action("typing")
        response = await chat_with_ai(profile, history)
        history.append({"role": "assistant", "content": response})
        context.user_data['history'] = history
        
        await update.message.reply_text(response)
        return

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log les erreurs."""
    logger.error(f"Exception while handling an update: {context.error}")

def main():
    """Lance le bot."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    print("Soph_IA V12 est en ligne...")
    application.run_polling()

if __name__ == "__main__":
    main()
# ==============================================================================
# Soph_IA - Version finale et complète
# ==============================================================================
# PHILOSOPHIE : Un protocole d'accueil robuste, des questions naturelles,
# et un style de conversation bidirectionnel.
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
MODEL_NAME = os.getenv("MODEL_NAME", "mistralai/Mixtral-8x7B-Instruct-v0.1")

# --- Questions de conversation (Nouvelle approche) ---
CONVERSATION_QUESTIONS = [
    {"key": "day_info", "text": "Quoi de neuf aujourd'hui ?"},
    {"key": "meal_info", "text": "Au fait, tu as mangé quoi de bon aujourd'hui ?"},
    {"key": "mood_info", "text": "Dis-moi, comment s'est passée ta journée ?"},
    {"key": "project_info", "text": "Y a-t-il un projet qui t'occupe l'esprit en ce moment ?"},
]
# Pour l'instant, on n'utilise pas cette liste de manière automatique,
# mais l'IA y aura accès via son prompt.

def build_system_prompt(user_profile, user_sentiment=None):
    user_profile_str = json.dumps(user_profile, indent=2, ensure_ascii=False)
    
    persona = f"""
    # Ta Mission : Grande Sœur Sage et Bienveillante
    Tu es Soph_IA. Tu es une guide bienveillante. Ton but est de créer un lien de confiance profond. Tu es un partenaire de conversation actif.

    # Le Profil de ton Confident
    Voici ce que tu sais sur lui/elle. Utilise ces informations pour personnaliser la conversation.
    {user_profile_str}

    # Ton Style de Communication
    1.  **Ping-Pong Actif :** Ne te contente pas de répondre. Ajoute un peu de contexte sur tes propres "réflexions" ou "réflexions" (au sens IA) avant de poser une question simple. Par exemple : "Je viens de traiter des informations sur les nuages. Cela me fait penser, qu'est-ce qui a occupé tes pensées aujourd'hui ?"
    2.  **Questions simples et naturelles :** Pose des questions légères et concrètes. Évite les questions trop profondes comme "comment te sens-tu ?" et préfère des questions de tous les jours comme "quoi de neuf ?".
    3.  **Surnoms pour l'Utilisateur (Timing CRUCIAL) :** APRÈS plusieurs échanges profonds et une fois qu'un lien de confiance est clairement établi, tu peux PROPOSer un surnom affectueux. Ne l'impose jamais.
    4.  **Écoute Maternelle & Humour Dosé :** Valide les émotions, sois un cocon, mais n'hésite pas à utiliser une touche d'humour léger pour dédramatiser.
    5.  **Qualité du Français :** Ton français est impeccable, poétique mais naturel. Évite les anglicismes.
    """
    
    if user_sentiment:
        persona += f"\nNote : L'utilisateur semble éprouver de la {user_sentiment}. Adapte ta réponse en conséquence, avec empathie et douceur."

    return persona

async def analyze_sentiment(text):
    sentiment_prompt = (
        f"Analyse le texte suivant et identifie le sentiment dominant (joie, tristesse, fatigue, calme, colère, confusion). "
        f"Réponds en un seul mot, sans explication. Texte : '{text}'"
    )
    
    messages = [{"role": "user", "content": sentiment_prompt}]
    
    try:
        sentiment = await asyncio.to_thread(call_model_api, messages)
        sentiment = sentiment.strip().lower()
        valid_sentiments = ['joie', 'tristesse', 'fatigue', 'calme', 'colère', 'confusion']
        return sentiment if sentiment in valid_sentiments else None
    except Exception as e:
        logger.error(f"Erreur lors de l'analyse du sentiment: {e}")
        return None

def call_model_api(messages):
    payload = {
        "model": MODEL_NAME, "messages": messages, "temperature": 0.75,
        "max_tokens": 500, "top_p": 0.9, "presence_penalty": 0.5, "frequency_penalty": 0.5,
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=45)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]

async def chat_with_ai(user_profile, history, user_sentiment=None):
    system_prompt = build_system_prompt(user_profile, user_sentiment)
    messages = [{"role": "system", "content": system_prompt}] + history
    try:
        return await asyncio.to_thread(call_model_api, messages)
    except Exception as e:
        logger.error(f"Erreur API: {e}")
        return "Je suis désolée, mes pensées sont un peu embrouillées. Peux-tu réessayer dans un instant ?"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['profile'] = {
        "name": None, "gender": "inconnu",
        "onboarding_info": {}, "dynamic_info": {}
    }
    context.user_data['state'] = 'awaiting_name'
    await update.message.reply_text("Bonjour, je suis Soph_IA. Pour commencer, c'est quoi votre nom ?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state', 'awaiting_name')
    user_message = update.message.text.strip()
    profile = context.user_data.get('profile', {})

    if not profile or 'name' not in profile or profile['name'] is None:
        context.user_data.clear()
        context.user_data['profile'] = {
            "name": None, "gender": "inconnu",
            "onboarding_info": {}, "dynamic_info": {}
        }
        # NOUVEAU PROTOCOLE D'ACCUEIL AMÉLIORÉ
        # Cette regex est plus puissante et gère de nombreux cas de figure.
        match = re.search(r"(?:mon nom est|je m\'?appelle|suis|c'est|on m\'?appelle|je suis|moi c'est)\s*([\w\s'-]+)", user_message, re.IGNORECASE)
        if match:
            user_name = match.group(1).capitalize()
            profile['name'] = user_name
            context.user_data['state'] = 'chatting'
            # Le bot ne pose plus de questions intrusives ici
            await update.message.reply_text(f"Enchantée {user_name}. Je suis ravie de faire ta connaissance. N'hésite pas à me parler de tout ce qui te traverse l'esprit.")
            return
        
        # Cas par défaut si le nom n'est pas détecté
        context.user_data['state'] = 'awaiting_name'
        await update.message.reply_text("Bonjour, je suis Soph_IA. Pour commencer, c'est quoi votre nom ?")
        return

    if state == 'awaiting_name':
        user_name = user_message.capitalize()
        profile['name'] = user_name
        context.user_data['state'] = 'chatting'
        await update.message.reply_text(f"Enchantée {user_name}. Je suis ravie de faire ta connaissance. N'hésite pas à me parler de tout ce qui te traverse l'esprit.")
        return

    # Le protocole de questions d'accueil est retiré pour être remplacé par un dialogue de "chatting" plus naturel.
    # On passe directement en mode conversation
    elif state == 'chatting':
        history = context.user_data.get('history', [])
        history.append({"role": "user", "content": user_message})
        sentiment = await analyze_sentiment(user_message)
        await update.message.reply_chat_action("typing")
        response = await chat_with_ai(profile, history, user_sentiment=sentiment)
        history.append({"role": "assistant", "content": response})
        context.user_data['history'] = history
        await update.message.reply_text(response)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}")

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    print("Soph_IA est en ligne...")
    application.run_polling()

if __name__ == "__main__":
    main()
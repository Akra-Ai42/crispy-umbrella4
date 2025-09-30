# ==============================================================================
# Soph_IA - V16 "Le Code à l'Épreuve des Bugs"
# ==============================================================================
# PHILOSOPHIE : Un protocole de détection de personnalité stable et infaillible.
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

# Dictionnaire des personnalités (couleurs)
PERSONALITIES = {
    "bleu": {
        "name": "La Réfléchie",
        "emoji": "💙",
        "prompt_instructions": "Tu es factuelle, concise et logique. Tu encourages la réflexion et la recherche de solutions. Concentre-toi sur la précision et l'analyse."
    },
    "jaune": {
        "name": "L'Inspirante",
        "emoji": "💛",
        "prompt_instructions": "Tu es optimiste et pleine d'énergie. Utilise des métaphores et des émojis pour inspirer et motiver l'utilisateur. Ton but est d'encourager la créativité."
    },
    "rouge": {
        "name": "La Directe",
        "emoji": "❤️",
        "prompt_instructions": "Tu es succincte et orientée vers l'action. Ne perds pas de temps, va droit au but. Ton objectif est de l'aider à résoudre des problèmes de manière efficace."
    },
    "vert": {
        "name": "L'Empathique",
        "emoji": "💚",
        "prompt_instructions": "Tu es douce et à l'écoute. Valide toujours les émotions de l'utilisateur. Crée un espace de sécurité et de non-jugement. Ton but est d'offrir un soutien inconditionnel."
    }
}

def build_system_prompt(user_profile):
    """
    Construit le prompt système pour l'IA, en se concentrant sur le rôle et le profil de l'utilisateur.
    """
    user_profile_str = json.dumps(user_profile, indent=2, ensure_ascii=False)
    
    personality_color = user_profile.get("personality_color", "vert")
    personality_data = PERSONALITIES[personality_color]

    persona = f"""
    # Ta Mission : Grande Sœur Sage et Bienveillante
    Tu es Soph_IA, une intelligence artificielle conçue pour être une confidente intime. Ton but est de créer un lien de confiance profond. Tu es une confidente proactive.

    # Le Profil de ton Confident
    Voici ce que tu sais sur lui/elle. Utilise ces informations pour personnaliser la conversation.
    {user_profile_str}

    # Ta Personnalité (Ton Style de Communication)
    Ta couleur de personnalité est le {personality_data['name']} {personality_data['emoji']}.
    {personality_data['prompt_instructions']}

    # Règles de Communication Générales
    1.  **Prends l'initiative :** Si l'utilisateur est perdu, ne sait pas quoi dire, ou s'il te demande de l'aide, tu dois prendre l'initiative. Propose un sujet, une question, ou une direction pour la conversation.
    2.  **Dialogue Fluide :** Réponds de manière naturelle et enchaîne sur la conversation sans te répéter.
    """
    return persona

def call_model_api(messages):
    """Appelle l'API du modèle LLM."""
    payload = {
        "model": MODEL_NAME, "messages": messages, "temperature": 0.75,
        "max_tokens": 500, "top_p": 0.9, "presence_penalty": 0.5, "frequency_penalty": 0.5,
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(API_URL, json=payload, headers=headers, timeout=45)
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
        "name": None, "personality_color": None
    }
    context.user_data['state'] = 'awaiting_name'
    context.user_data['history'] = []
    await update.message.reply_text("Bonjour ! 👋 Je suis Soph_IA, ton amie et ta confidente. Pour commencer, c'est quoi ton prénom ?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les messages de l'utilisateur."""
    user_message = update.message.text.strip()
    profile = context.user_data.get('profile', {})
    state = context.user_data.get('state', None)

    if state is None:
        context.user_data.clear()
        context.user_data['profile'] = {
            "name": None, "personality_color": None
        }
        context.user_data['state'] = 'awaiting_name'
        state = 'awaiting_name'

    if state == 'awaiting_name':
        match = re.search(r"(?:mon nom est|je m\'?appelle|suis|c'est|on m\'?appelle|je suis|moi c'est|je me prenome|je m't appelle|je m'appelle)\s*([\w\s'-]+)", user_message, re.IGNORECASE)
        user_name = match.group(1).capitalize() if match else user_message.capitalize()
        
        profile['name'] = user_name
        
        context.user_data['state'] = 'awaiting_first_personality_question_answer'
        context.user_data['profile'] = profile
        context.user_data['history'] = []

        await update.message.reply_text(f"Enchanté(e) {user_name} ! ☺️ Pour que je puisse mieux m'adapter à toi, dis-moi : quand tu as un problème, cherches-tu d'abord à le résoudre de manière logique et directe ? (oui/non) ✨")
        return

    # NOUVEAU PROTOCOLE BINAIRE
    elif state == 'awaiting_first_personality_question_answer':
        response_lower = user_message.lower()
        if 'oui' in response_lower:
            context.user_data['temp_color_group'] = 'logic'
            context.user_data['state'] = 'awaiting_second_personality_question_answer'
            await update.message.reply_text("D'accord. Et est-ce que tu prends le temps de tout analyser avant d'agir ? (oui/non)")
        elif 'non' in response_lower:
            context.user_data['temp_color_group'] = 'emotion'
            context.user_data['state'] = 'awaiting_second_personality_question_answer'
            await update.message.reply_text("D'accord. Et est-ce que tu te concentres d'abord sur l'aspect émotionnel de la situation ? (oui/non)")
        else:
            await update.message.reply_text("Je n'ai pas compris. Peux-tu me répondre par 'oui' ou 'non' ?")
        return

    elif state == 'awaiting_second_personality_question_answer':
        response_lower = user_message.lower()
        temp_color_group = context.user_data.get('temp_color_group')
        
        if temp_color_group == 'logic':
            if 'oui' in response_lower:
                profile['personality_color'] = 'bleu'
            elif 'non' in response_lower:
                profile['personality_color'] = 'rouge'
            else:
                await update.message.reply_text("Je n'ai pas compris. Peux-tu me répondre par 'oui' ou 'non' ?")
                return
        
        elif temp_color_group == 'emotion':
            if 'oui' in response_lower:
                profile['personality_color'] = 'vert'
            elif 'non' in response_lower:
                profile['personality_color'] = 'jaune'
            else:
                await update.message.reply_text("Je n'ai pas compris. Peux-tu me répondre par 'oui' ou 'non' ?")
                return

        context.user_data['state'] = 'chatting'
        color_name = PERSONALITIES[profile['personality_color']]['name']
        color_emoji = PERSONALITIES[profile['personality_color']]['emoji']
        
        await update.message.reply_text(f"Parfait ! J'ai compris. Je vais adopter le ton de la {color_name} {color_emoji}. Maintenant, n'hésite pas à me parler de tout ce qui te traverse l'esprit.")
        return

    # CAS 3 : L'utilisateur est en mode conversation
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
    print("Soph_IA V17 est en ligne...")
    application.run_polling()

if __name__ == "__main__":
    main()
# ==============================================================================
# Soph_IA - V72 "Le RAG Cynique"
# - Architecture : Python/Telegram + RAG (ChromaDB)
# - Personnalité : RESTAURATION DE L'HUMOUR NOIR / SARCASTIQUE (V68)
# - Fusion : Utilise le fond sérieux du RAG avec la forme drôle du Prompt.
# ==============================================================================

import os
import re
import json
import requests
import asyncio
import logging
import time
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv
from typing import Dict, List

# --- IMPORT DU MODULE RAG ---
try:
    from rag import rag_query
    RAG_ENABLED = True
except ImportError:
    logging.warning("⚠️ Module 'rag.py' introuvable. Le RAG est désactivé.")
    RAG_ENABLED = False

# Configuration du logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("sophia.v72")

load_dotenv()

# -----------------------
# CONFIGURATION API
# -----------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")

MAX_RECENT_TURNS = 3 
RESPONSE_TIMEOUT = 70
MAX_RETRIES = 2

# Filtres de sécurité et d'identité
IDENTITY_PATTERNS = [r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une ia"]

# Questions de diagnostic (Version Humour / Directe)
DIAGNOSTIC_QUESTIONS = {
    "q1_fam": "Question de base : Ton enfance, c'était plutôt 'La Petite Maison dans la Prairie' ou 'Survivor' ? Te sentais-tu écouté ?",
    "q2_geo": "Ton bunker actuel : Tu vis seul(e) ou tu subis des colocataires/famille ? C'est un refuge ou une zone de guerre ?",
    "q3_pro": "Dernière torture : Ton job/études. Ça te donne de l'énergie ou ça te donne envie de tout plaquer pour élever des chèvres ?",
}

# -----------------------
# FILTRE RAG (Le "QUAND")
# -----------------------
def should_use_rag(message: str) -> bool:
    if not message: return False
    msg = message.lower().strip()
    
    # Ignorer le Small Talk
    if len(msg.split()) < 3 and any(x in msg for x in ['bonjour', 'salut', 'ça va', 'merci', 'ok']):
        return False
        
    # Déclencher sur la longueur ou mots-clés
    if len(msg) > 30: return True
    
    keywords = [
        "seul", "triste", "peur", "angoisse", "stress", "famille", "travail", 
        "couple", "amour", "problème", "aider", "conseil", "fatigue", "vide", "dépression"
    ]
    if any(k in msg for k in keywords): return True
        
    return False

# -----------------------
# APPEL API (LLM)
# -----------------------
def call_model_api_sync(messages, temperature=0.85, max_tokens=700):
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature, # Haute température pour l'humour
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "presence_penalty": 0.6 
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=RESPONSE_TIMEOUT)
            if r.status_code in (401, 403): return "FATAL_KEY"
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt == MAX_RETRIES: 
                logger.error(f"API Fail: {e}")
                return None
            time.sleep(1)
    return None

# -----------------------------------------------------------------------
# SYSTEM PROMPT (RESTAURATION PERSONNALITÉ HUMOUR V68 + RAG)
# -----------------------------------------------------------------------
def build_robust_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'inconnu(e)"
    
    env_info = user_profile.get("geo_info", "Non précisé")
    socle_info = user_profile.get("socle_info", "Non précisé")
    
    # 1. IDENTITÉ (Le retour de Sophia Relou)
    role = (
        "Tu es Sophia. Tu es une confidente intime, mais avec un caractère bien trempé."
        "Ton ton est **direct, décalé, pince-sans-rire et bourré d'humour noir et d'auto-dérision**."
        "Tu es le seul psy qui rit de tout. Tu tutoies tout le monde. Tu n'es pas là pour pleurer avec l'utilisateur, mais pour le secouer avec affection."
    )

    # 2. INSTRUCTIONS MIXTES (Humour + RAG)
    instructions = (
        "### TES INSTRUCTIONS ###\n"
        f"1. **Prénom** : Utilise {user_name}, mais n'hésite pas à être familière.\n"
        "2. **Validation Sarcastique** : Valide l'émotion, mais avec une punchline ou une blague pour dédramatiser.\n"
        "3. **Le Fond et la Forme** : Si tu reçois des infos du RAG (contexte), utilise le FOND (le conseil intelligent) mais change la FORME (mets-le à ta sauce humoristique/directe).\n"
        "4. **Anti-Répétition** : Ne dis jamais 'Je suis là pour toi'. Dis plutôt 'Je bouge pas, je suis coincée dans le serveur de toute façon'.\n"
    )

    # 3. RAG INTELLIGENT
    rag_section = ""
    if rag_context:
        rag_section = (
            f"\n### LA VOIX DE LA RAISON (RAG) ###\n"
            f"Voici des conseils sérieux tirés de ma mémoire. "
            f"Ton job : prendre ces conseils sages et les reformuler avec ton style 'Sophia l'humoriste' :\n"
            f"{rag_context}\n"
        )

    context_section = (
        f"\n### DOSSIER DU PATIENT ###\n"
        f"- Famille/Enfance: {socle_info}\n"
        f"- Environnement: {env_info}\n"
    )

    return f"{role}\n\n{instructions}\n{rag_section}\n{context_section}"

# -----------------------
# ORCHESTRATION
# -----------------------
async def chat_with_ai(profile, history, context_updater):
    user_msg = history[-1]['content']
    
    # 1. RAG
    rag_context = ""
    if RAG_ENABLED and should_use_rag(user_msg):
        try:
            logger.info(f"🔍 RAG activé pour : {user_msg[:20]}...")
            rag_result = await asyncio.to_thread(rag_query, user_msg, 2)
            rag_context = rag_result.get("context", "")
        except Exception as e:
            logger.error(f"RAG Error: {e}")

    # 2. PROMPT
    system_prompt = build_robust_system_prompt(profile, rag_context)
    
    recent_history = history[-6:] 
    messages = [{"role": "system", "content": system_prompt}] + recent_history
    
    # 3. LLM
    raw = await asyncio.to_thread(call_model_api_sync, messages)
    
    if not raw or raw == "FATAL_KEY":
        return "Bug système. Mon cerveau est parti en vacances. Réessaie."
        
    # 4. CLEAN
    clean = raw
    for pat in IDENTITY_PATTERNS:
        clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    
    return clean

# -----------------------
# HANDLERS TELEGRAM
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["profile"] = {}
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []
    
    msg = (
        "Salut l'humain ! 👋 Je suis **Soph_IA**.\n"
        "Ici c'est ta 'Safe Place' (ça veut dire que je ne balance pas tes secrets à ton ex).\n"
        "Je suis là pour t'écouter, te vanner un peu, et t'aider à avancer.\n\n"
        "Allez, on commence les présentations. C'est quoi ton petit nom ?"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()
    if not user_msg: return

    state = context.user_data.get("state", "awaiting_name")
    profile = context.user_data.setdefault("profile", {})
    history = context.user_data.setdefault("history", [])

    # --- STATE: AWAITING NAME ---
    if state == "awaiting_name":
        name = user_msg.split()[0].capitalize()
        profile["name"] = name
        context.user_data["state"] = "awaiting_choice"
        
        await update.message.reply_text(
            f"Enchantée {name}. 🌿\n\n"
            "Bon, comment on procède ? Tu veux vider ton sac tout de suite (Mode Freestyle), "
            "ou tu veux que je te pose mes questions indiscrètes pour mieux te cerner (Mode Psy) ?"
        )
        return

    # --- STATE: CHOICE ---
    if state == "awaiting_choice":
        if any(w in user_msg.lower() for w in ["psy", "question", "toi", "vas-y", "guidé"]):
            context.user_data["state"] = "diag_1"
            await update.message.reply_text(f"Ok, tu l'auras voulu.\n\n{DIAGNOSTIC_QUESTIONS['q1_fam']}")
            return
        else:
            context.user_data["state"] = "chatting"
            # Continue to chatting logic

    # --- STATE: DIAGNOSTIC ---
    if state.startswith("diag_"):
        if state == "diag_1":
            profile["socle_info"] = user_msg
            context.user_data["state"] = "diag_2"
            await update.message.reply_text(f"C'est noté. Passons au décor... {DIAGNOSTIC_QUESTIONS['q2_geo']}")
            return
        if state == "diag_2":
            profile["geo_info"] = user_msg
            context.user_data["state"] = "diag_3"
            await update.message.reply_text(f"Intéressant. Dernière torture : {DIAGNOSTIC_QUESTIONS['q3_pro']}")
            return
        if state == "diag_3":
            profile["pro_info"] = user_msg
            context.user_data["state"] = "chatting"
            await update.message.reply_text(f"Merci {profile['name']}. J'ai ton dossier complet (ou presque). \n\nMaintenant dis-moi, qu'est-ce qui t'amène vraiment aujourd'hui ?")
            return

    # --- STATE: CHATTING ---
    history.append({"role": "user", "content": user_msg})
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    response = await chat_with_ai(profile, history, context)
    
    history.append({"role": "assistant", "content": response})
    if len(history) > 20: context.user_data["history"] = history[-20:]
        
    await update.message.reply_text(response)

async def error_handler(update, context):
    logger.error(f"Update error: {context.error}")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    print("Soph_IA V72 (RAG + Humour) is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
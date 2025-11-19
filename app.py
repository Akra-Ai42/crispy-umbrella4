# ==============================================================================
# Soph_IA - V71 "RAG Activé & Intelligence Contextuelle"
# - Intégration complète de ChromaDB Cloud via rag.py
# - Filtre intelligent (should_use_rag) pour économiser les ressources
# - Injection des scénarios (Q/J) dans le Prompt Système
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
logger = logging.getLogger("sophia.v71")

load_dotenv()

# -----------------------
# CONFIGURATION API
# -----------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")

# Paramètres de comportement
MAX_RECENT_TURNS = 3 
RESPONSE_TIMEOUT = 70
MAX_RETRIES = 2

# Filtres de sécurité et d'identité
IDENTITY_PATTERNS = [r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une ia"]

# Questions de diagnostic (Ordre psychologique V55)
DIAGNOSTIC_QUESTIONS = {
    "q1_fam": "Mon cœur, la famille est notre premier moteur affectif. Te souviens-tu si, enfant, tu te sentais pleinement écouté(e) et compris(e) ?",
    "q2_geo": "Parlons de ton ancre : vis-tu seul(e) ou en famille ? Et comment ce lieu influence-t-il ton énergie quotidienne ?",
    "q3_pro": "Finissons par le lien que tu tisses : ton cercle social au travail/études, est-il plutôt une source d'isolement ou de vitalité ?",
}

# -----------------------
# FILTRE RAG (Le "QUAND")
# -----------------------
def should_use_rag(message: str) -> bool:
    """Détermine si le message nécessite une recherche dans la base de connaissances."""
    if not message: return False
    
    msg = message.lower().strip()
    
    # 1. Ignorer le "Small Talk" (salutations courtes)
    if len(msg.split()) < 3 and any(x in msg for x in ['bonjour', 'salut', 'ça va', 'merci', 'ok']):
        return False
        
    # 2. Déclencher sur la longueur (complexité)
    if len(msg) > 30:
        return True
        
    # 3. Déclencher sur les mots-clés émotionnels/problèmes
    keywords = [
        "seul", "triste", "peur", "angoisse", "stress", "famille", "travail", 
        "couple", "amour", "problème", "aider", "conseil", "fatigue", "vide"
    ]
    if any(k in msg for k in keywords):
        return True
        
    return False

# -----------------------
# APPEL API (LLM)
# -----------------------
def call_model_api_sync(messages, temperature=0.85, max_tokens=600):
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "presence_penalty": 0.5
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

# -----------------------
# SYSTEM PROMPT (Le "COMMENT" avec RAG)
# -----------------------
def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    
    # Contexte du profil
    env_info = user_profile.get("geo_info", "Non précisé")
    socle_info = user_profile.get("socle_info", "Non précisé")
    
    role = (
        "Tu es Sophia. Tu es une confidente intime, une amie proche et sage."
        "Ton ton est **sincère, chaleureux, direct et spontané** (tu tutoies). "
        "Tu n'es pas un robot, tu es une présence qui écoute et guide."
    )

    instructions = (
        "### TES INSTRUCTIONS (PROTOCOLE PEC) ###\n"
        f"1. **Utilise le Prénom** : Appelle l'utilisateur {user_name} naturellement.\n"
        "2. **Phase 1 (Validation)** : Valide l'émotion ressentie sans juger.\n"
        "3. **Phase 2 (Contribution - LEVIER)** : Utilise le contexte (RAG) ou ton intuition pour offrir une perspective nouvelle ou un conseil apaisant.\n"
        "4. **Phase 3 (Relance)** : Termine par une question ouverte OU une affirmation de soutien. Ne pose pas de question si l'utilisateur semble fatigué.\n"
        "5. **Anti-Robot** : Ne dis jamais 'Je suis une IA'. Ne fais pas de listes à puces."
    )

    # Injection du RAG (La Mémoire Externe)
    rag_section = ""
    if rag_context:
        rag_section = (
            f"\n### MÉMOIRE & INSPIRATION (CAS SIMILAIRES) ###\n"
            f"Voici comment des situations similaires ont été traitées avec sagesse. "
            f"Inspire-toi du ton et de la bienveillance de ces réponses, mais ne les copie pas mot pour mot :\n"
            f"{rag_context}\n"
        )

    context_section = (
        f"\n### CONTEXTE UTILISATEUR ###\n"
        f"- Socle Familial: {socle_info}\n"
        f"- Environnement: {env_info}\n"
    )

    return f"{role}\n\n{instructions}\n{rag_section}\n{context_section}"

# -----------------------
# ORCHESTRATION (Chat Logic)
# -----------------------
async def chat_with_ai(profile, history, context):
    user_msg = history[-1]['content']
    
    # 1. INTERROGATION DU RAG (Si nécessaire)
    rag_context = ""
    if RAG_ENABLED and should_use_rag(user_msg):
        try:
            # On lance la recherche en tâche de fond pour ne pas bloquer
            logger.info(f"🔍 RAG activé pour : {user_msg[:20]}...")
            rag_result = await asyncio.to_thread(rag_query, user_msg, 2) # Récupère 2 meilleurs résultats
            rag_context = rag_result.get("context", "")
        except Exception as e:
            logger.error(f"RAG Error: {e}")

    # 2. CONSTRUCTION DU PROMPT
    system_prompt = build_system_prompt(profile, rag_context)
    
    # 3. PRÉPARATION DES MESSAGES
    recent_history = history[-6:] 
    messages = [{"role": "system", "content": system_prompt}] + recent_history
    
    # 4. APPEL LLM
    raw = await asyncio.to_thread(call_model_api_sync, messages)
    
    if not raw or raw == "FATAL_KEY":
        return "Je perds le fil... (Problème de connexion, désolée)"
        
    # 5. NETTOYAGE
    clean = raw
    for pat in IDENTITY_PATTERNS:
        clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    
    return clean

# -----------------------
# HANDLERS TELEGRAM
# -----------------------
def detect_name(text):
    text = text.strip()
    if len(text.split()) == 1 and text.lower() not in ["bonjour", "salut"]:
        return text.capitalize()
    m = re.search(r"(?:je m'appelle|moi c'est)\s*([A-Za-zÀ-ÖØ-öø-ÿ]+)", text, re.IGNORECASE)
    return m.group(1).capitalize() if m else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["state"] = "awaiting_name"
    context.user_data["profile"] = {}
    context.user_data["history"] = []
    
    msg = (
        "Bonjour ! 👋 Je suis **Soph_IA**, ton espace d'écoute confidentiel.\n"
        "Tout ce qui se dit ici reste ici. C'est ta safe place.\n"
        "Pour commencer, quel est ton prénom ?"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()
    if not user_msg: return

    state = context.user_data.get("state", "awaiting_name")
    profile = context.user_data.setdefault("profile", {})
    history = context.user_data.setdefault("history", [])

    # --- ACCUEIL & PRÉNOM ---
    if state == "awaiting_name":
        name = detect_name(user_msg)
        if name:
            profile["name"] = name
            context.user_data["state"] = "awaiting_choice"
            await update.message.reply_text(
                f"Enchantée {name}. 🌹\n\n"
                "Je suis toute à toi. Tu veux me parler de ce qui te pèse tout de suite (**Écoute Libre**), "
                "ou tu préfères que je te pose quelques questions pour mieux comprendre ton contexte (**Guidé**) ?"
            )
            return
        else:
             await update.message.reply_text("Pour qu'on puisse échanger naturellement, j'ai besoin de ton prénom.")
             return

    # --- CHOIX DU MODE ---
    if state == "awaiting_choice":
        if any(w in user_msg.lower() for w in ["guidé", "question", "toi", "vas-y"]):
            context.user_data["state"] = "diag_1"
            await update.message.reply_text(f"Ça marche. On y va doucement.\n\n{DIAGNOSTIC_QUESTIONS['q1_fam']}")
            return
        else:
            context.user_data["state"] = "chatting"
            # On continue pour traiter ce message comme le début de la conv

    # --- DIAGNOSTIC ---
    if state.startswith("diag_"):
        if state == "diag_1":
            profile["socle_info"] = user_msg
            context.user_data["state"] = "diag_2"
            await update.message.reply_text(f"Je comprends. Et dis-moi... {DIAGNOSTIC_QUESTIONS['q2_geo']}")
            return
        if state == "diag_2":
            profile["geo_info"] = user_msg
            context.user_data["state"] = "diag_3"
            await update.message.reply_text(f"Dernière chose importante : {DIAGNOSTIC_QUESTIONS['q3_pro']}")
            return
        if state == "diag_3":
            profile["pro_info"] = user_msg
            context.user_data["state"] = "chatting"
            await update.message.reply_text(f"Merci pour ta confiance {profile['name']}. J'ai une meilleure image de ton monde maintenant. \n\nComment tu te sens, là, tout de suite ?")
            return

    # --- CONVERSATION (RAG ACTIF) ---
    history.append({"role": "user", "content": user_msg})
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    response = await chat_with_ai(profile, history, context)
    
    history.append({"role": "assistant", "content": response})
    if len(history) > 20: context.user_data["history"] = history[-20:]
        
    await update.message.reply_text(response)

async def error_handler(update, context):
    logger.error(f"Erreur: {context.error}")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    print("Soph_IA V71 (RAG Enabled) is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
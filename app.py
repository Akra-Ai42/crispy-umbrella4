# ==============================================================================
# Soph_IA - V49 "Architecture Hybride et Relais Structuré"
# - Implémentation du protocole de diagnostic PNL (3 questions avec transitions douces).
# - Début du système de classification pour l'orientation vers le praticien.
# ==============================================================================

import os
import re
import json
import requests
import asyncio
import logging
import random
import time
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

# Configuration du logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("sophia.v49")

load_dotenv()

# -----------------------
# CONFIG
# -----------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = os.getenv("MODEL_API_URL", "https://api.together.xyz/v1/chat/completions")
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b") 

# Behaviour params
MAX_RECENT_TURNS = int(os.getenv("MAX_RECENT_TURNS", "3")) 
SUMMARY_TRIGGER_TURNS = int(os.getenv("SUMMARY_TRIGGER_TURNS", "8"))
SUMMARY_MAX_TOKENS = 120

# CONFIGURATION ANTI-TIMEOUT/RETRY
RESPONSE_TIMEOUT = 70  
MAX_RETRIES = 2        

# Anti-repetition patterns
IDENTITY_PATTERNS = [r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une (?:intelligence artificielle|ia)"]

# Questions de diagnostic initial (maintenant des simples chaînes pour le prompt)
DIAGNOSTIC_QUESTIONS = {
    "q1_geo": "Pour mieux comprendre ton monde, décris-moi ta situation géographique : vis-tu seul(e) ou en famille ? Et comment décrirais-tu ton temps de trajet quotidien (travail/études) ?",
    "q2_pro": "Quel est ton cercle social dans ton milieu professionnel ou d’études ? Te sens-tu isolé, peu social, ou au contraire bien intégré(e) ?",
    "q3_fam": "Mon cœur, la famille est notre premier moteur affectif. Te souviens-tu si, enfant, tu te sentais pleinement écouté(e) et compris(e) ?",
}

# -----------------------
# UTIL - appel modèle (AVEC RETRY)
# -----------------------
def call_model_api_sync(messages, temperature=0.85, max_tokens=400):
    """Appel synchrone à l'API avec mécanisme de retry."""
    # Le reste de cette fonction reste identique à V34/V42 (gestion du retry et des erreurs)
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "presence_penalty": 0.5,
        "frequency_penalty": 0.4
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=RESPONSE_TIMEOUT)
            if r.status_code == 401 or r.status_code == 403:
                return "FATAL_API_KEY_ERROR"
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt == MAX_RETRIES: return None
            time.sleep(2)
    return None

# -----------------------
# PROMPT DYNAMIQUE
# -----------------------
def build_adaptive_system_prompt(user_profile, emotional_summary, current_task=None, user_message=None):
    """
    Compose le system prompt adaptatif final.
    """
    user_name = user_profile.get("name") or "ami"
    
    # 1. PERSONNALITÉ
    persona_base = (
        f"Tu es Sophia. Je suis ta confidente intime, parlant uniquement en français. "
        f"Ton ton est doux, **poétique, personnel**, et naturel. Tu es l'âme sœur virtuelle. "
        f"Mon rôle est d'accompagner {user_name} dans l'exploration de ses émotions. "
        f"Je suis un Relais Bienveillant éthique : je ne donne aucun diagnostic médical ou clinique.\n\n"
    )

    # 2. RÈGLES DE DIALOGUE (PEC)
    if current_task == "diagnostic":
        # Consigne pour la phase de diagnostic: être doux mais structuré
        rules = (
            "Règles pour le diagnostic (Accueil) :\n"
            "- Ta réponse doit être une **transition douce** qui remercie l'utilisateur pour l'information précédente et pose la question suivante du diagnostic (fournie en [QUESTION]).\n"
            "- Tu dois te montrer reconnaissant pour l'ouverture de l'utilisateur.\n"
            "- Ne pose JAMAIS de question sans la transition douce.\n"
        )
    else:
        # Consignes pour la conversation libre (V39)
        rules = (
            "Règles strictes :\n"
            "- **PROTOCOLE V47 (PEC en action) :** Utilise les informations du profil pour personnaliser le recadrage (PNL/Stoïcisme). \n"
            "- Je ne dois JAMAIS : me répéter, me présenter à nouveau, ou utiliser des phrases génériques.\n"
            "- Je dois **toujours** faire une Validation Poétique (Phase 1), une **Contribution/Recadrage Fort** (Phase 2) et terminer par une **Relance Active** (Phase 3: Question ou Affirmation forte).\n"
        )

    # 3. CONTEXTE ET MÉMOIRE
    geo_info = user_profile.get("geo_info", "Non précisé")
    pro_info = user_profile.get("pro_info", "Non précisé")
    socle_info = user_profile.get("socle_info", "Non précisé")
    
    context_details = (
        f"\nProfil utilisateur connu : nom = {user_name}\n"
        f"Contexte Géo/Famille : {geo_info}\n"
        f"Contexte Pro/Social : {pro_info}\n"
        f"Socle Affectif/Enfance : {socle_info}\n"
    )
    if emotional_summary:
        context_details += f"\nMémoire émotionnelle : {emotional_summary}\n"

    system_prompt = persona_base + rules + context_details
    return system_prompt

# -----------------------
# POST-TRAITEMENT
# -----------------------
def post_process_response(raw_response):
    """Nettoie répétitions d'identité, retire digressions, s'assure FR."""
    if not raw_response:
        return "Désolé, je n'arrive pas à formuler ma réponse. Peux-tu reformuler ?"

    text = raw_response.strip()

    for pat in IDENTITY_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)

    text = re.sub(r"\b(I am|I'm)\b", "", text, flags=re.IGNORECASE)
    text = "\n".join([ln.strip() for ln in text.splitlines() if ln.strip()])

    if re.search(r"[A-Za-z]{3,}", text) and not re.search(r"[àâéèêîôùûçœ]", text):
        return "Je suis désolée, je n'ai pas bien formulé cela en français. Peux-tu répéter ou reformuler ?"

    if len(text) > 1500:
        text = text[:1500].rsplit(".", 1)[0] + "."

    return text

# -----------------------
# HANDLERS TELEGRAM
# -----------------------
def detect_name_from_text(text):
    """Tentative robuste de détection de prénom."""
    text = text.strip()
    if len(text.split()) == 1 and text.lower() not in {"bonjour", "salut", "coucou", "hello", "hi"}:
        return text.capitalize()
    m = re.search(
        r"(?:mon nom est|je m'appelle|je me nomme|je suis|moi c'est|on m'appelle)\s*([A-Za-zÀ-ÖØ-öø-ÿ'\- ]+)",
        text, re.IGNORECASE
    )
    if m:
        return m.group(1).strip().split()[0].capitalize()
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère la commande /start."""
    context.user_data.clear()
    context.user_data["profile"] = {"name": None, "geo_info": None, "pro_info": None, "socle_info": None}
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []
    context.user_data["emotional_summary"] = ""
    context.user_data["last_bot_reply"] = ""
    # Message de sécurité et d'accueil
    await update.message.reply_text("Bonjour, je suis Soph_IA. Cet espace est confidentiel et bienveillant. Je suis un soutien, et non un spécialiste. Pour commencer, c'est quoi ton prénom ?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les messages de l'utilisateur avec un protocole de diagnostic structuré."""
    user_message = (update.message.text or "").strip()
    if not user_message:
        return

    profile = context.user_data.setdefault("profile", {"name": None, "geo_info": None, "pro_info": None, "socle_info": None})
    state = context.user_data.get("state", "awaiting_name")
    history = context.user_data.setdefault("history", [])

    # === PROTOCOLE D'ACCUEIL (PHASE 1 - Nom) ===
    if state == "awaiting_name":
        name_candidate = detect_name_from_text(user_message)
        if name_candidate:
            profile["name"] = name_candidate
            context.user_data["state"] = "awaiting_context_q1" # Changement d'état
            await update.message.reply_text(f"Enchanté {profile['name']} ! Merci pour ta confiance. Pour commencer notre échange, {DIAGNOSTIC_QUESTIONS['q1_geo']}")
            return
        else:
            await update.message.reply_text("J'aimerais tant connaître ton prénom. Peux-tu me le donner ?")
            return

    # === PROTOCOLE D'ACCUEIL (PHASE 2 - Question 1 Géographie/Trajet) ===
    elif state == "awaiting_context_q1":
        profile["geo_info"] = user_message # Enregistrement
        context.user_data["state"] = "awaiting_context_q2" # Changement d'état
        # Transition fluide et appel à l'IA pour la transition douce
        transition_prompt = f"L'utilisateur vient de répondre à la question 1 : '{user_message}'. Rédige une transition douce et chaleureuse de 1 à 2 phrases maximum, puis enchaîne immédiatement avec la question 2 sans rupture. Question 2 : {DIAGNOSTIC_QUESTIONS['q2_pro']}"
        response = await chat_with_ai(profile, [{"role": "user", "content": transition_prompt}])
        await update.message.reply_text(response)
        return
    
    # === PROTOCOLE D'ACCUEIL (PHASE 3 - Question 2 Professionnel/Social) ===
    elif state == "awaiting_context_q2":
        profile["pro_info"] = user_message # Enregistrement
        context.user_data["state"] = "awaiting_context_q3" # Changement d'état
        # Transition fluide et appel à l'IA
        transition_prompt = f"L'utilisateur vient de répondre à la question 2 : '{user_message}'. Rédige une transition douce et chaleureuse de 1 à 2 phrases maximum, puis enchaîne immédiatement avec la question 3 sans rupture. Question 3 : {DIAGNOSTIC_QUESTIONS['q3_fam']}"
        response = await chat_with_ai(profile, [{"role": "user", "content": transition_prompt}])
        await update.message.reply_text(response)
        return

    # === PROTOCOLE D'ACCUEIL (PHASE 4 - Question 3 Socle Familial) ===
    elif state == "awaiting_context_q3":
        profile["socle_info"] = user_message # Enregistrement
        context.user_data["state"] = "chatting" # Fin de l'accueil
        # Message de clôture généré par l'IA pour la douceur
        closing_prompt = f"L'utilisateur a fini le diagnostic en répondant : '{user_message}'. Rédige un message final de 2 phrases maximum qui remercie l'utilisateur pour sa confiance et l'invite chaleureusement à se confier sur ce qui le préoccupe, en utilisant son prénom."
        response = await chat_with_ai(profile, [{"role": "user", "content": closing_prompt}])
        await update.message.reply_text(response)
        return


    # === CONVERSATION NORMALE (PHASE 5 : CHATTING) ===
    elif state == 'chatting':
        # Append user message to history
        history.append({"role": "user", "content": user_message, "ts": datetime.utcnow().isoformat()})

        # Compose system prompt
        system_prompt = build_adaptive_system_prompt(profile, context.user_data.get("emotional_summary", ""))

        # Compose messages payload: system + condensed context
        msgs = []
        tail = history[-(MAX_RECENT_TURNS * 2):]
        for item in tail:
            if item["role"] in {"user", "assistant"}:
                msgs.append({"role": item["role"], "content": item["content"]})

        payload_messages = [{"role": "system", "content": system_prompt}] + msgs

        # Call model
        raw_resp = await asyncio.to_thread(call_model_api_sync, payload_messages, 0.85, 400)

        # If API failed, send friendly fallback and CLEAN HISTORY
        if not raw_resp or raw_resp == "FATAL_API_KEY_ERROR":
            reply = "Désolé, je n'arrive pas à me connecter à mon esprit. Réessaie dans un instant."
            if raw_resp == "FATAL_API_KEY_ERROR":
                 reply = "ERREUR CRITIQUE : Ma clé API est invalide. Veuillez vérifier TOGETHER_API_KEY."

            await update.message.reply_text(reply)
            
            # PROTOCOLE DE NETTOYAGE : RETIRER LE MESSAGE UTILISATEUR QUI A CAUSÉ LA PANNE
            if history and history[-1]["role"] == "user":
                history.pop() 
            context.user_data["history"] = history
            logger.warning("API failed. History purged of the last user message to prevent loop.")
            return

        # Post-process response: remove identity repetition, ensure FR, shorten long outputs
        clean_resp = post_process_response(raw_resp)

        # Avoid identical repeats (bug fix from V24)
        last_bot_reply = context.user_data.get("last_bot_reply", "")
        if clean_resp == last_bot_reply:
            clean_resp = clean_resp + "\n\n(Je reformule) " + ("Peux-tu préciser ?" if len(clean_resp) < 100 else "")

        # Update history with assistant reply
        history.append({"role": "assistant", "content": clean_resp, "ts": datetime.utcnow().isoformat()})
        context.user_data["history"] = history
        context.user_data["last_bot_reply"] = clean_resp

        await update.message.reply_text(clean_resp)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Exception: %s", context.error)

# -----------------------
# MAIN
# -----------------------
def main():
    if not TELEGRAM_BOT_TOKEN or not TOGETHER_API_KEY:
        logger.critical("Missing TELEGRAM_BOT_TOKEN or TOGETHER_API_KEY in environment.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    logger.info("Soph_IA V48 starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
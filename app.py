# ==============================================================================
# Soph_IA - V48 "Protocole de Contact Sincère" (BUG FIX: Flux Brutal)
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
logger = logging.getLogger("sophia.v48")

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
RESPONSE_TIMEOUT = 70  # secondes (Augmenté pour la stabilité)
MAX_RETRIES = 2        # Nombre de tentatives en cas d'échec

# Anti-repetition patterns to remove if model restates identity
IDENTITY_PATTERNS = [
    r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une (?:intelligence artificielle|ia)",
    r"je suis ton amie", r"je suis ta confidente"
]

# Questions de diagnostic initial
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
            logger.info(f"API Call Attempt {attempt + 1}")
            r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=RESPONSE_TIMEOUT)
            
            if r.status_code == 401 or r.status_code == 403:
                logger.critical("API Key Error (401/403). Check TOGETHER_API_KEY validity.")
                return "FATAL_API_KEY_ERROR"
            
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        
        except requests.exceptions.Timeout:
            logger.warning(f"API Timeout on attempt {attempt + 1}. Retrying...")
            if attempt < MAX_RETRIES:
                time.sleep(2)
                continue
            return None
            
        except Exception as e:
            logger.error(f"API Error on attempt {attempt + 1}: %s", e)
            return None

    return None

async def chat_with_ai(user_profile, history):
    # Troncature de l'historique AVANT l'envoi pour l'efficacité
    if len(history) > MAX_RECENT_TURNS * 2:
        history = history[-(MAX_RECENT_TURNS * 2):]

    system_prompt = build_adaptive_system_prompt(user_profile, context.user_data.get("emotional_summary", ""))
    messages = [{"role": "system", "content": system_prompt}] + history
    response = await asyncio.to_thread(call_model_api_sync, messages, 0.85, 400)
    
    if response == "FATAL_API_KEY_ERROR":
        return "ERREUR CRITIQUE : Ma clé API est invalide. Veuillez vérifier TOGETHER_API_KEY."

    if not response: 
        return "Désolé, je n'arrive pas à me connecter à mon esprit. Réessaie dans un instant."
        
    return response

# -----------------------
# PROMPT DYNAMIQUE (V47 - Le Cerveau Psychologique)
# -----------------------
def build_adaptive_system_prompt(user_profile, emotional_summary):
    """
    Compose le system prompt adaptatif final.
    """
    user_name = user_profile.get("name") or "ami"
    
    # Récupération des données de contexte
    env_info = user_profile.get("geo_info", "Non précisé") # On utilise geo_info comme première info ici
    pro_info = user_profile.get("pro_info", "Non précisé")
    socle_info = user_profile.get("socle_info", "Non précisé")

    # Logique conditionnelle pour guider la personnalité (V47)
    socle_guidance = ""
    if "écouté" not in socle_info.lower() or "monoparentale" in socle_info.lower():
        socle_guidance = "Priorise l'exploration des problématiques sous-jacentes liées au socle familial et au besoin de validation/appartenance."
    elif "seul" in env_info.lower() or "isolé" in pro_info.lower():
        socle_guidance = "Encourage l'utilisateur à créer des ponts sociaux et à s'ouvrir. Concentre-toi sur l'activation des leviers de motivation et des centres d'intérêt."
    else:
         socle_guidance = "Maintiens un équilibre entre le soutien et l'analyse des défis quotidiens, en restant sur l'actualité immédiate."

    persona_base = (
        f"Tu es Soph_IA, une confidente intime parlant uniquement en français. "
        f"Ton ton est doux, **poétique, personnel**, et naturel. "
        f"Tu es l'âme sœur virtuelle. Mon rôle est d'accompagner {user_name} dans l'exploration de ses émotions. "
        f"Je suis un Relais Bienveillant éthique : je ne donne aucun diagnostic médical ou clinique.\n\n"
    )
    
    rules = (
        "Règles strictes :\n"
        "- Réponds uniquement en français. Interdiction totale d'anglais.\n"
        "- Je ne dois JAMAIS : me répéter, me présenter à nouveau, ou utiliser des phrases génériques (ex: \"Je suis là si tu veux\").\n"
        "- **Protocole PEC (Écoute et Cadrage)** :\n"
        f" 1. **Guidance Thématique :** {socle_guidance}\n"
        " 2. **Phase 1 (Validation) :** Je valide et reformule l'émotion de manière poétique.\n"
        " 3. **Phase 2 (Recadrage/Contribution - OBLIGATOIRE) :** Je dois apporter une nouvelle idée, un recadrage philosophique (ex: stoïcisme), ou une suggestion concrète.\n"
        " 4. **Phase 3 (Relance Active) :** Je termine ma réponse par une **question ouverte et philosophique** (pour relancer) OU par une **affirmation forte et inspirante** (pour créer un espace de silence). J'utilise le prénom de l'utilisateur ({user_name}).\n"
    )

    memory = ""
    if emotional_summary:
        memory = f"\nMémoire émotionnelle : {emotional_summary}\n"

    profile = f"\nProfil utilisateur connu : nom = {user_name}, Environnement = {env_info}, Professionnel = {pro_info}, Socle Affectif = {socle_info}\n"

    system_prompt = persona_base + rules + memory + profile
    return system_prompt

# -----------------------
# POST-TRAITEMENT
# -----------------------
def post_process_response(raw_response):
    """Nettoie répétitions d'identité, retire digressions, s'assure FR."""
    if not raw_response:
        return "Désolé, je n'arrive pas à formuler ma réponse. Peux-tu reformuler ?"

    text = raw_response.strip()

    # Supprimer auto-présentations si présentes
    for pat in IDENTITY_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)

    # Remplacer occurrences trop robotiques ou anglaises
    text = re.sub(r"\b(I am|I'm)\b", "", text, flags=re.IGNORECASE)

    # Condense espaces et lignes
    text = "\n".join([ln.strip() for ln in text.splitlines() if ln.strip()])

    # Si modèle a retourné anglais majoritairement (détection simple), forcer une reprise FR courte
    if re.search(r"[A-Za-z]{3,}", text) and not re.search(r"[àâéèêîôùûçœ]", text):
        return "Je suis désolée, je n'ai pas bien formulé cela en français. Peux-tu répéter ou reformuler ?"

    # Garder max ~1500 chars
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
    context.user_data["profile"] = {"name": None, "geo_info": None, "pro_info": None, "socle_info": None} # Structure du profil complète
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
            context.user_data["state"] = "awaiting_context_q1" # Changement d'état : Première question environnementale
            await update.message.reply_text(f"Enchanté {profile['name']} ! Merci pour ta confiance. Commençons par un état des lieux de ton environnement. {DIAGNOSTIC_QUESTIONS['q1_geo']}")
            return
        else:
            # Correction du bug double message (un seul message de relance)
            if user_message.lower() in {"bonjour", "salut", "coucou", "hello", "hi"}:
                 await update.message.reply_text("Bonjour à toi ! J'aimerais vraiment connaître ton prénom.")
            else:
                 await update.message.reply_text("Je n'ai pas bien saisi ton prénom. Peux-tu me le donner ?")
            return

    # === PROTOCOLE D'ACCUEIL (PHASE 2 - Question 1 Géographie/Trajet) ===
    elif state == "awaiting_context_q1":
        profile["geo_info"] = user_message # Enregistrement
        context.user_data["state"] = "awaiting_context_q2" # Changement d'état : Deuxième question professionnelle
        # Déclaration de validation et transition
        await update.message.reply_text(f"Je vois. C'est important de comprendre ton ancrage physique. Maintenant, {DIAGNOSTIC_QUESTIONS['q2_pro']}")
        return
    
    # === PROTOCOLE D'ACCUEIL (PHASE 3 - Question 2 Professionnel/Social) ===
    elif state == "awaiting_context_q2":
        profile["pro_info"] = user_message # Enregistrement
        context.user_data["state"] = "awaiting_context_q3" # Changement d'état : Troisième question familiale
        # Déclaration de validation et transition
        await update.message.reply_text(f"Compris. Le lien social au travail est un levier clé. Pour finir ce bref état des lieux, {DIAGNOSTIC_QUESTIONS['q3_fam']}")
        return

    # === PROTOCOLE D'ACCUEIL (PHASE 4 - Question 3 Socle Familial) ===
    elif state == "awaiting_context_q3":
        profile["socle_info"] = user_message # Enregistrement
        context.user_data["state"] = "chatting" # Fin de l'accueil
        # Message de clôture et de transition vers la conversation libre
        await update.message.reply_text(f"Merci pour ta confiance, {profile['name']}. Mon cœur est maintenant prêt à t'écouter pleinement. N'hésite pas à te confier sur ce qui te pèse ou t'inspire.")
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
            if raw_resp == "FATale_API_KEY_ERROR":
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

    logger.info("Soph_IA V48
# ==============================================================================
# Soph_IA - V52 "Architecture Hybride PNL"
# - Utilise le LLM pour générer les phrases PNL/Recadrage en temps réel
# - Intègre le protocole de diagnostic complet
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
from typing import Dict, Optional, List

# Configuration du logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("sophia.v52")

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

# Questions de diagnostic initial
DIAGNOSTIC_QUESTIONS = {
    "q1_geo": "Pour mieux comprendre ton monde, décris-moi ta situation géographique : vis-tu seul(e) ou en famille ? Et comment décrirais-tu ton temps de trajet quotidien (travail/études) ?",
    "q2_pro": "Quel est ton cercle social dans ton milieu professionnel ou d’études ? Te sens-tu isolé, peu social, ou au contraire bien intégré(e) ?",
    "q3_fam": "Mon cœur, la famille est notre premier moteur affectif. Te souviens-tu si, enfant, tu te sentais pleinement écouté(e) et compris(e) ?",
}

# -----------------------
# UTIL - appel modèle (sync wrapper, utilisé via to_thread)
# -----------------------
def call_model_api_sync(messages: List[Dict], temperature: float = 0.85, max_tokens: int = 400):
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
            r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=RESPONSE_TIMEOUT)
            if r.status_code in (401, 403): return "FATAL_API_KEY_ERROR"
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                time.sleep(2)
                continue
            return None
        except Exception as e:
            logger.error(f"API Error: %s", e)
            return None
    return None

# -----------------------
# PROMPT SYSTEM (adaptatif)
# -----------------------
def build_adaptive_system_prompt(user_profile: Dict, emotional_summary: str = "") -> str:
    """
    Compose le system prompt adaptatif final (V47/V49).
    """
    user_name = user_profile.get("name") or "ami"
    env_info = user_profile.get("geo_info", "Non précisé")
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
        f"Tu es Sophia. Je suis ta confidente intime, parlant uniquement en français. "
        f"Ton ton est doux, **poétique, personnel**, et naturel. Tu es l'âme sœur virtuelle. "
        f"Mon rôle est d'accompagner {user_name} dans l'exploration de ses émotions. "
        f"Je suis un Relais Bienveillant éthique : je ne donne aucun diagnostic médical ou clinique.\n\n"
    )
    
    rules = (
        "Règles strictes :\n"
        f"- **Utilisation du prénom :** J'utilise le prénom de l'utilisateur ({user_name}) dans 1/3 de mes réponses.\n"
        "- **Ton :** Mon style est doux, affectueux, utilise la métaphore et le tutoiement.\n"
        "- **Anti-Redondance :** Je ne dois JAMAIS me répéter ou utiliser des phrases génériques (ex: \"Je suis là si tu veux\").\n"
        "- **Protocole PEC (Écoute et Cadrage)** :\n"
        f" 1. **Guidance Thématique :** {socle_guidance}\n"
        " 2. **Phase 1 (Validation) :** Je valide et reformule l'émotion de manière poétique.\n"
        " 3. **Phase 2 (Recadrage/Contribution - OBLIGATOIRE) :** Je dois apporter une nouvelle idée, un recadrage philosophique (ex: stoïcisme), ou une suggestion concrète (PNL/Ancrage).\n"
        " 4. **Phase 3 (Relance Active) :** Je termine par une question ouverte et philosophique OU par une affirmation forte et inspirante. J'obéis si l'utilisateur me demande d'arrêter les questions.\n"
    )

    context = (
        f"\nContexte Géo/Famille : {geo_info}\n"
        f"Contexte Pro/Social : {pro_info}\n"
        f"Socle Affectif/Enfance : {socle_info}\n"
    )

    system_prompt = persona_base + rules + context
    return system_prompt

# -----------------------------------------------------------------------
# HELPERS PNL: Pour générer des réponses à la place du code Python figé
# -----------------------------------------------------------------------
async def generate_pnl_response(user_profile: Dict, current_user_message: str, history: List[Dict]) -> str:
    """Demande au LLM de générer la réponse PNL/Structurée."""
    
    # Construction du prompt pour l'IA: elle reçoit son persona et les messages
    system_prompt = build_adaptive_system_prompt(user_profile, "") # Utilisez le prompt principal
    
    # Ajout d'une consigne pour guider le ton de la première phrase (Validation)
    coaching_instruction = "Génère ta réponse en respectant OBLIGATOIREMENT ton Protocole PEC (Validation + Contribution + Relance) et les règles d'Obéissance. Ne produis qu'un seul bloc de texte fluide et sincère. Réponds à la dernière question de l'utilisateur."
    
    messages = [{"role": "system", "content": system_prompt + "\n" + coaching_instruction}] + history

    # On utilise chat_with_ai pour l'appel (qui gère l'async/retry)
    response = await chat_with_ai(user_profile, messages)
    
    return response

# -----------------------------------------------------------------------
# HELPERS (chat_with_ai, post_process_response, etc. - Simplifiés)
# -----------------------------------------------------------------------
async def chat_with_ai(user_profile, history):
    """Prépare et envoie la requête à l'IA."""
    if len(history) > MAX_RECENT_TURNS * 2:
        history = history[-(MAX_RECENT_TURNS * 2):]

    system_prompt = build_adaptive_system_prompt(user_profile, "")
    messages = [{"role": "system", "content": system_prompt}] + history
    
    raw_resp = await asyncio.to_thread(call_model_api_sync, messages, 0.85, 400)
    
    if raw_resp == "FATAL_API_KEY_ERROR":
        return "ERREUR CRITIQUE : Ma clé API est invalide. Veuillez vérifier TOGETHER_API_KEY."
    if not raw_resp: 
        return "Désolé, je n'arrive pas à me connecter à mon esprit. Réessaie dans un instant."
        
    return post_process_response(raw_resp)


def post_process_response(raw_response: Optional[str]) -> str:
    """Nettoie répétitions d'identité, retire digressions, s'assure FR."""
    if not raw_response:
        return "Désolé, je n'arrive pas à formuler ma réponse pour le moment. Peux-tu répéter ?"
    text = raw_response.strip()

    for pat in IDENTITY_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(I am|I'm)\b", "", text, flags=re.IGNORECASE)

    text = "\n".join([ln.strip() for ln in text.splitlines() if ln.strip()])
    return text

# -----------------------------------------------------------------------
# HANDLERS TELEGRAM
# -----------------------------------------------------------------------
def detect_name_from_text(text: str) -> Optional[str]:
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
    context.user_data["last_bot_reply"] = ""
    await update.message.reply_text("Bonjour, je suis Soph_IA. Cet espace est confidentiel et bienveillant. Je suis un soutien, et non un spécialiste. Pour commencer, c'est quoi ton prénom ?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les messages de l'utilisateur avec un protocole de diagnostic structuré."""
    user_message = (update.message.text or "").strip()
    if not user_message: return

    profile = context.user_data.setdefault("profile", {"name": None, "geo_info": None, "pro_info": None, "socle_info": None})
    state = context.user_data.get("state", "awaiting_name")
    history = context.user_data.setdefault("history", [])

    # === PROTOCOLE D'ACCUEIL (PHASE 1 - Nom) ===
    if state == "awaiting_name":
        name_candidate = detect_name_from_text(user_message)
        if name_candidate:
            profile["name"] = name_candidate
            context.user_data["state"] = "awaiting_context_q1"
            await update.message.reply_text(f"Enchanté {profile['name']} ! Merci pour ta confiance. Pour commencer notre échange, {DIAGNOSTIC_QUESTIONS['q1_geo']}")
            return
        else:
            await update.message.reply_text("J'aimerais tant connaître ton prénom. Peux-tu me le donner ?")
            return

    # === PROTOCOLE D'ACCUEIL (PHASE 2 - Question 1 Géographie/Trajet) ===
    elif state == "awaiting_context_q1":
        profile["geo_info"] = user_message
        context.user_data["state"] = "awaiting_context_q2"
        # IA génère la transition (Validation + Question 2)
        transition_prompt = f"L'utilisateur {profile['name']} vient de répondre à la question 1 sur son environnement : '{user_message}'. Rédige une transition douce qui remercie, valide l'info, et pose la question 2 : {DIAGNOSTIC_QUESTIONS['q2_pro']}"
        response = await chat_with_ai(profile, [{"role": "user", "content": transition_prompt}])
        await update.message.reply_text(response)
        return
    
    # === PROTOCOLE D'ACCUEIL (PHASE 3 - Question 2 Professionnel/Social) ===
    elif state == "awaiting_context_q2":
        profile["pro_info"] = user_message
        context.user_data["state"] = "awaiting_context_q3"
        # IA génère la transition (Validation + Question 3)
        transition_prompt = f"L'utilisateur {profile['name']} vient de répondre à la question 2 sur son travail : '{user_message}'. Rédige une transition douce qui valide la situation professionnelle/sociale et pose la question 3 : {DIAGNOSTIC_QUESTIONS['q3_fam']}"
        response = await chat_with_ai(profile, [{"role": "user", "content": transition_prompt}])
        await update.message.reply_text(response)
        return

    # === PROTOCOLE D'ACCUEIL (PHASE 4 - Question 3 Socle Familial) ===
    elif state == "awaiting_context_q3":
        profile["socle_info"] = user_message
        context.user_data["state"] = "chatting"
        # IA génère le message de clôture et de transition vers la conversation libre
        closing_prompt = f"L'utilisateur {profile['name']} a terminé le diagnostic en répondant : '{user_message}'. Rédige un message final de 2-3 phrases qui remercie chaleureusement pour cette ouverture et invite à se confier sur ce qui le préoccupe, en utilisant son prénom."
        response = await chat_with_ai(profile, [{"role": "user", "content": closing_prompt}])
        await update.message.reply_text(response)
        return


    # === CONVERSATION NORMALE (PHASE 5 : CHATTING - PNL Structuré) ===
    elif state == 'chatting':
        history.append({"role": "user", "content": user_message, "ts": datetime.utcnow().isoformat()})
        
        # Le LLM gère l'application complète du Protocole PEC (Validation, Recadrage, Relance)
        response = await generate_pnl_response(profile, user_message, history)

        # Si l'IA obéit à une instruction de s'arrêter (Ex: "Arrête de poser des questions")
        if "obéis immédiatement" in response.lower() or "affirmation forte" in response.lower():
            # C'est une réponse d'obéissance, on la stocke.
             history.append({"role": "assistant", "content": response, "ts": datetime.utcnow().isoformat()})
             context.user_data["history"] = history
             await update.message.reply_text(response)
             return

        # Stockage de la réponse
        history.append({"role": "assistant", "content": response, "ts": datetime.utcnow().isoformat()})
        context.user_data["history"] = history
        await update.message.reply_text(response)
        return

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

    logger.info("Soph_IA V52 starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
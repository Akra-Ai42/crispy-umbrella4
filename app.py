# ==============================================================================
# Soph_IA - V57 "Affichage du Message de Sécurité et Protocole Stabilisé"
# - Correction critique de l'affichage du message de bienvenue.
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

# Configuration du logging (inchangée)
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("sophia.v57")

load_dotenv()

# --- CONFIG (Inchangé) ---
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

# Questions de diagnostic initial (Ordre V55 conservé)
DIAGNOSTIC_QUESTIONS = {
    "q1_fam": "Mon cœur, la famille est notre premier moteur affectif. Te souviens-tu si, enfant, tu te sentais pleinement écouté(e) et compris(e) ?",
    "q2_geo": "Parlons de ton ancre : vis-tu seul(e) ou en famille ? Et comment ce lieu influence-t-il ton énergie quotidienne ?",
    "q3_pro": "Finissons par le lien que tu tisses : ton cercle social au travail/études, est-il plutôt une source d'isolement ou de vitalité ?",
}

# -----------------------
# UTIL - appel modèle (sync wrapper, utilisé via to_thread)
# -----------------------
def call_model_api_sync(messages: List[Dict], temperature: float = 0.85, max_tokens: int = 400):
    # (Logique de l'appel API inchangée)
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
            if attempt == MAX_RETRIES: return None
            time.sleep(2)
        except Exception as e:
            logger.error(f"API Error: %s", e)
            return None
    return None

async def chat_with_ai(user_profile: Dict, history: List[Dict], temperature: float = 0.85, max_tokens: int = 400) -> str:
    # (Logique de l'appel LLM inchangée)
    if history and len(history) > 0 and history[-1].get("role") == "user":
        if len(history) > MAX_RECENT_TURNS * 2:
            history = history[-(MAX_RECENT_TURNS * 2):]

    system_prompt = build_adaptive_system_prompt(user_profile, context.user_data.get("emotional_summary", ""))
    
    payload_messages = [{"role": "system", "content": system_prompt}] + history
    
    raw_resp = await asyncio.to_thread(call_model_api_sync, payload_messages, temperature, max_tokens)
    
    if raw_resp == "FATAL_API_KEY_ERROR":
        return "ERREUR CRITIQUE : Ma clé API est invalide. Veuillez vérifier TOGETHER_API_KEY."
    if not raw_resp: 
        return "Désolé, je n'arrive pas à me connecter à mon esprit. Réessaie dans un instant."
        
    return post_process_response(raw_resp)

# -----------------------
# PROMPT DYNAMIQUE (V47/V55)
# -----------------------
def build_adaptive_system_prompt(user_profile, emotional_summary):
    # (Le prompt reste inchangé, centré sur le rôle et les règles PNL)
    user_name = user_profile.get("name") or "ami"
    env_info = user_profile.get("geo_info", "Non précisé")
    pro_info = user_profile.get("pro_info", "Non précisé")
    socle_info = user_profile.get("socle_info", "Non précisé")

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
    # (Logique de post-traitement inchangée)
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
    # (Logique de détection de nom inchangée)
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
    
    # --- CORRECTION CRITIQUE ICI : Message de bienvenue fusionné ---
    accueil_message = (
        "Bonjour ! 👋 Je suis **Soph_IA**, ton espace d'écoute. "
        "Je suis là pour t'accompagner, sans jugement ni diagnostic. "
        "Sache que **tout ce que tu me confies reste confidentiel**. C'est ta safe place. "
        "Pour commencer notre échange, quel est ton prénom ou ton surnom ? ✨"
    )
    await update.message.reply_text(accueil_message, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les messages de l'utilisateur avec un protocole de diagnostic structuré."""
    user_message = (update.message.text or "").strip()
    if not user_message: return

    profile = context.user_data.setdefault("profile", {"name": None, "geo_info": None, "pro_info": None, "socle_info": None})
    state = context.user_data.get("state", "awaiting_name")
    history = context.user_data.setdefault("history", [])

    # === ÉTAPE 1 : NOM ===
    if state == "awaiting_name":
        name_candidate = detect_name_from_text(user_message)
        if name_candidate:
            profile["name"] = name_candidate
            context.user_data["state"] = "awaiting_mode_choice" # Nouvelle étape
            
            # Message de confirmation et proposition du choix
            choice_message = (
                f"Enchanté {profile['name']} ! 🌹 Je suis ravie de faire ta connaissance.\n\n"
                "Maintenant que nous avons posé les bases de confiance... "
                "**Allez, dis-moi : je suis tout à toi (Mode Écoute Libre), ou tu veux que ce soit moi qui parle (Mode Diagnostic) ?** 🤔"
            )
            await update.message.reply_text(choice_message)
            return
        else:
             await update.message.reply_text("Pour qu'on puisse échanger plus naturellement, quel est ton prénom ou surnom ?")
             return

    # === ÉTAPE 2 : CHOIX DE PROTOCOLE (Logique d'accueil avancée) ===
    elif state == "awaiting_mode_choice":
        response_lower = user_message.lower()
        
        # KEYWORDS FOR MODE 2: GUIDED DIAGNOSTIC (The user wants Sophia to lead or is ambiguous/hesitant)
        diagnostic_keywords = ['moi qui parle', 'diagnostic', 'questions', 'toi', 'toi qui enchaîne', 'je sais pas', 'sais pas parler', 'comme tu veux', 'enchaîne', 'harceler', 'oui', 'non']
        
        # KEYWORDS FOR MODE 1: ECOUTE LIBRE (The user wants to speak)
        listening_keywords = ['tout à toi', 'je parle', 'écoute libre', 'moi d\'abord'] 

        # 1. Check for explicit choice of LISTENING mode (Mode 1) OR spontaneous sharing
        if any(k in response_lower for k in listening_keywords) or (len(user_message.split()) > 4 and not any(q in response_lower for q in diagnostic_keywords)):
            # Mode 1: Écoute Active - On passe directement au mode 'chatting' et on traite le message en cours.
            context.user_data["state"] = "chatting"
            
            # Traitement immédiat du message de l'utilisateur avec le Protocole PEC
            history.append({"role": "user", "content": user_message, "ts": datetime.utcnow().isoformat()})
            response = await chat_with_ai(profile, history) 
            
            if "ERREUR CRITIQUE" in response or "Désolé, je n'arrive pas à me connecter" in response:
                 await update.message.reply_text(response)
                 return

            history.append({"role": "assistant", "content": response, "ts": datetime.utcnow().isoformat()})
            context.user_data["history"] = history
            await update.message.reply_text(response)
            return
        
        # 2. Check for GUIDED mode OR ambiguous/harassment response (Mode 2 - Diagnostic)
        elif any(k in response_lower for k in diagnostic_keywords):
            context.user_data["state"] = "awaiting_context_q1_fam"
            await update.message.reply_text(f"Parfait, j'enclenche le mode 'exploration douce', {profile['name']}. Ce n'est pas toujours simple de choisir, je prends les commandes pour un départ en douceur.")
            await update.message.reply_text(f"Commençons par la fondation de ton cœur : {DIAGNOSTIC_QUESTIONS['q1_fam']}")
            return
        
        else:
            await update.message.reply_text("Je n'ai pas bien saisi. Dis-moi si tu as envie de **parler tout de suite** (je suis à toi) ou si tu préfères que ce soit **moi qui enchaîne avec quelques questions**.")
            return


    # === PROTOCOLE D'ACCUEIL GUIDÉ (Q1 Familial) ===
    elif state == "awaiting_context_q1_fam":
        profile["socle_info"] = user_message # Enregistrement
        context.user_data["state"] = "awaiting_context_q2_geo" # Nouvelle Q2
        # IA génère la transition (Validation + Question 2)
        transition_prompt = f"L'utilisateur {profile['name']} vient de répondre à la question 1 sur son socle familial : '{user_message}'. Rédige une transition douce et chaleureuse de 1 à 2 phrases maximum, puis enchaîne immédiatement avec la question 2 sans rupture. Question 2 : {DIAGNOSTIC_QUESTIONS['q2_geo']}"
        response = await chat_with_ai(profile, [{"role": "user", "content": transition_prompt}])
        await update.message.reply_text(response)
        return
    
    # === PROTOCOLE D'ACCUEIL GUIDÉ (Q2 Géographie/Ancrage) ===
    elif state == "awaiting_context_q2_geo":
        profile["geo_info"] = user_message # Enregistrement
        context.user_data["state"] = "awaiting_context_q3_pro" # Nouvelle Q3
        # IA génère la transition (Validation + Question 3)
        transition_prompt = f"L'utilisateur {profile['name']} vient de répondre à la question 2 sur son lieu de vie : '{user_message}'. Rédige une transition douce et chaleureuse de 1 à 2 phrases maximum, puis enchaîne immédiatement avec la question 3 sans rupture. Question 3 : {DIAGNOSTIC_QUESTIONS['q3_pro']}"
        response = await chat_with_ai(profile, [{"role": "user", "content": transition_prompt}])
        await update.message.reply_text(response)
        return

    # === PROTOCOLE D'ACCUEIL GUIDÉ (Q3 Professionnel/Social) ===
    elif state == "awaiting_context_q3_pro":
        profile["pro_info"] = user_message # Enregistrement
        context.user_data["state"] = "chatting" # Fin de l'accueil
        # Message de clôture généré par l'IA
        closing_prompt = f"L'utilisateur {profile['name']} a terminé le diagnostic en répondant : '{user_message}'. Rédige un message final de 2-3 phrases qui remercie chaleureusement pour sa confiance, valide la profondeur des partages, et l'invite à se confier sur ce qui le préoccupe, en utilisant son prénom."
        response = await chat_with_ai(profile, [{"role": "user", "content": closing_prompt}])
        await update.message.reply_text(response)
        return


    # === CONVERSATION NORMALE (PHASE CHATTING) ===
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

    logger.info("Soph_IA V57 starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
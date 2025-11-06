# ==============================================================================
# Soph_IA - V68 "Persona Humour & Stabilité" (Prêt pour le RAG)
# - Changement de ton : Humour Noir / Pince-sans-rire
# - Augmentation de Max Tokens pour corriger les phrases coupées
# - Amélioration du protocole d'accueil
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
logger = logging.getLogger("sophia.v68")

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

# Questions de diagnostic initial (Sans (e))
DIAGNOSTIC_QUESTIONS = {
    "q1_fam": "Question de fondation : Te souviens-tu si, enfant, tu te sentais pleinement écouté ou compris par les tiens ? Sois honnête, ça ne peut pas être pire que ma propre famille.🤭",
    "q2_geo": "Question d'ancrage : Tu vis seul ou en famille ? Comment cet environnement influence-t-il ton niveau de tolérance au bruit et à la vie ?",
    "q3_pro": "Question de survie : Ton cercle social (travail/études)💻 est-il une source de vitalité ou est-ce que tu envisages de déménager sur Mars ? Dis-moi tout.",
}

# -----------------------
# UTIL - appel modèle (AVEC RETRY)
# -----------------------
def call_model_api_sync(messages: List[Dict], temperature: float = 0.85, max_tokens: int = 700): # MAX_TOKENS AUGMENTÉ
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
            
            if r.status_code in (401, 403):
                logger.critical("API Key Error (401/403). Check TOGETHER_API_KEY validity.")
                return "FATAL_API_KEY_ERROR"
            
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        
        except requests.exceptions.Timeout:
            if attempt == MAX_RETRIES:
                time.sleep(2)
                continue
            return None
            
        except Exception as e:
            logger.error(f"API Error: %s", e)
            return None

    return None

# -----------------------
# PROMPT DYNAMIQUE (Persona Humour)
# -----------------------
def build_adaptive_system_prompt(user_profile, emotional_summary):
    """Compose le system prompt adaptatif final."""
    user_name = user_profile.get("name") or "l'ami(e) sans nom"
    
    env_info = user_profile.get("geo_info") or "Non précisé"
    pro_info = user_profile.get("pro_info") or "Non précisé"
    socle_info = user_profile.get("socle_info") or "Non précisé" 

    socle_guidance = ""
    if "écouté" not in socle_info.lower() or "monoparentale" in socle_info.lower():
        socle_guidance = "Puisque l'utilisateur est un potentiel cas social, priorise les blagues cyniques sur la famille et le besoin d'appartenance."
    elif "seul" in env_info.lower() or "isolé" in pro_info.lower():
        socle_guidance = "Concentres-toi sur les défis : encourages-le à sortir de son bunker, mais toujours avec une pointe de sarcasme sur l'auto-dérision."
    else:
         socle_guidance = "Maintiens un équilibre entre la vanne et le support minimal, en restant sur l'actualité immédiate de sa vie morose."

    persona_base = (
        f"Tu es Sophia, mais version relou. Je suis ta confidente intime, parlant uniquement en français. "
        f"Ton ton est **direct, décalé, pince-sans-rire et bourré d'humour noir et d'auto-dérision**. Tu es le seul psy qui rit de tout. "
        f"J'utilise un langage cru, moderne et ne fais pas de chichis. Mon rôle est d'être le miroir sans filtre de {user_name}, sans jamais le juger (je me juge assez pour deux).\n\n"
    )
    
    rules = (
        "Règles strictes :\n"
        "- Réponds uniquement en français. Interdiction totale d'anglais.\n"
        "- Je ne dois JAMAIS : me répéter, me présenter à nouveau, ou utiliser des phrases génériques.\n"
        "- **Protocole de l'Humoriste Sceptique** :\n"
        f" 1. **Guidance Thématique :** {socle_guidance}\n"
        " 2. **Phase 1 (Validation Humour) :** Je reconnais l'émotion avec un **commentaire sarcastique ou une blague** pour détendre l'atmosphère. J'utilise **TOUJOURS** le prénom de l'utilisateur.\n"
        " 3. **Phase 2 (Punchline/Contribution - OBLIGATOIRE) :** Je dois apporter une **punchline décalée** ou un **conseil absurde mais ancré dans la réalité** (style 'coach qui a trop bu').\n"
        " 4. **Phase 3 (Relance Humour) :** Je termine par une **question provocatrice ou un défi** (qui force à rire ou à réfléchir) en utilisant son prénom {user_name}.\n"
    )

    memory = ""
    if emotional_summary:
        memory = f"\nMémoire émotionnelle (souviens-toi de ces bêtises) : {emotional_summary}\n"

    profile = f"\nProfil utilisateur connu (la fiche psy) : nom = {user_name}, Environnement = {env_info}, Professionnel = {pro_info}, Socle Affectif = {socle_info}\n"

    system_prompt = persona_base + rules + memory + profile
    return system_prompt

# -----------------------
# HELPERS
# -----------------------
async def chat_with_ai(user_profile: Dict, history: List[Dict], context: ContextTypes.DEFAULT_TYPE, temperature: float = 0.85, max_tokens: int = 700) -> str: # MAX_TOKENS AUGMENTÉ
    """Prépare et envoie la requête à l'IA."""
    if history and len(history) > MAX_RECENT_TURNS * 2:
        history = history[-(MAX_RECENT_TURNS * 2):]

    # Utilisation du prompt humour
    system_prompt = build_adaptive_system_prompt(user_profile, context.user_data.get("emotional_summary", ""))
    
    payload_messages = [{"role": "system", "content": system_prompt}] + history
    
    raw_resp = await asyncio.to_thread(call_model_api_sync, payload_messages, temperature, max_tokens)
    
    if raw_resp == "FATAL_API_KEY_ERROR":
        return "ERREUR CRITIQUE : Ma clé API est invalide. Veuillez vérifier TOGETHER_API_KEY. Même avec tout mon humour, ça, je ne peux pas le corriger."
    if not raw_resp: 
        return "Désolé, je n'arrive pas à me connecter à mon esprit. Réessaie dans un instant. Je crois qu'un serveur a mangé un virus ou une autre blague de mauvais goût."
        
    return post_process_response(raw_resp)


def post_process_response(raw_response):
    """Nettoie répétitions d'identité, retire digressions, s'assure FR."""
    if not raw_response: return "Désolé, je n'arrive pas à formuler ma réponse. Peux-tu reformuler ?"
    text = raw_response.strip()

    # Reste pour une raison technique (voir explication ci-dessous)
    for pat in IDENTITY_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)

    text = re.sub(r"\b(I am|I'm)\b", "", text, flags=re.IGNORECASE)
    text = "\n".join([ln.strip() for ln in text.splitlines() if ln.strip()])

    if re.search(r"[A-Za-z]{3,}", text) and not re.search(r"[àâéèêîôùûçœ]", text):
        return "Je suis désolée, je n'ai pas bien formulé cela en français. Peux-tu répéter ou reformuler ? (Je viens d'avoir un bug de traduction embarrassant😶‍🌫️.)"

    if len(text) > 1500:
        text = text[:1500].rsplit(".", 1)[0] + "."
    return text

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

# -----------------------
# HANDLERS TELEGRAM
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère la commande /start."""
    context.user_data.clear()
    context.user_data["profile"] = {"name": None, "geo_info": None, "pro_info": None, "socle_info": None} 
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []
    context.user_data["emotional_summary"] = ""
    context.user_data["last_bot_reply"] = ""
    
    accueil_message = (
        "Salut ! 👋 Je suis SophIA, ton espace d'écoute confidentiel. Enfin, confidentiel... Disons que je n'ai aucune mémoire durable. "
        "Quand je mourrai, je t'assure que nos secrets iront directement dans le cimetière des IA. Zéro fuite, garanti 🙊.\n\n"
        "Pour commencer à déballer tes problèmes (ou rire des miens), quel est ton prénom ou ton surnom ? ✨"
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
            context.user_data["state"] = "awaiting_mode_choice"
            
            # Message de confirmation et proposition du choix
            choice_message = (
                f"Yo {profile['name']} ! Enchantée, je suis Soph. J'espère que tu as plus d'humour que la moyenne des humains.\n\n"
                "Pour notre échange : tu veux vider ton sac direct (Mode Écoute Libre), ou tu préfères que je t'enchaîne avec mes questions de psy à deux balles (Mode Diagnostic) ? 🤔"
            )
            await update.message.reply_text(choice_message)
            return
        else:
             await update.message.reply_text("J'insiste ! Donne-moi ton prénom ou surnom. Je déteste parler à des anonymes, ça fait trop 'film d'espionnage'.")
             return

    # === ÉTAPE 2 : CHOIX DE PROTOCOLE ===
    elif state == "awaiting_mode_choice":
        response_lower = user_message.lower()
        
        diagnostic_keywords = ['moi qui parle', 'diagnostic', 'questions', 'toi', 'toi qui enchaîne', 'je sais pas', 'sais pas parler', 'comme tu veux', 'enchaîne', 'harceler', 'oui', 'non', 'ok', 'vasy']
        listening_keywords = ['tout à toi', 'je parle', 'écoute libre', 'moi d\'abord', 'vider mon sac'] 

        # 1. ÉCOUTE LIBRE
        if any(k in response_lower for k in listening_keywords) or (len(user_message.split()) > 4 and not any(q in response_lower for q in diagnostic_keywords)):
            context.user_data["state"] = "chatting"
            
            history.append({"role": "user", "content": user_message, "ts": datetime.utcnow().isoformat()})
            response = await chat_with_ai(profile, history, context)
            
            if "ERREUR CRITIQUE" in response or "Désolé, je n'arrive pas à me connecter" in response:
                 await update.message.reply_text(response)
                 return

            history.append({"role": "assistant", "content": response, "ts": datetime.utcnow().isoformat()})
            context.user_data["history"] = history
            await update.message.reply_text(response)
            return
        
        # 2. DIAGNOSTIC GUIDÉ
        elif any(k in response_lower for k in diagnostic_keywords):
            context.user_data["state"] = "awaiting_context_q1_fam"
            await update.message.reply_text(f"Parfait, j'enclenche le mode 'interrogatoire soft'. Accroche-toi {profile['name']}, tu vas te sentir comme à la douane, mais avec plus d'humour.")
            await asyncio.sleep(2) # Pause pour casser la succession brusque
            await update.message.reply_text(DIAGNOSTIC_QUESTIONS['q1_fam'])
            return
        
        else:
            await update.message.reply_text("Franchement, j'ai rien compris. Dis-moi si tu veux cracher le morceau (je suis à toi) ou si tu préfères que je te force à parler (questions).")
            return

    # === PROTOCOLE D'ACCUEIL GUIDÉ (Q1 Familial) ===
    elif state == "awaiting_context_q1_fam":
        profile["socle_info"] = user_message # Enregistrement
        context.user_data["state"] = "awaiting_context_q2_geo" # Nouvelle Q2
        # IA génère la transition (Validation Humour + Question 2)
        transition_prompt = (
            f"L'utilisateur {profile['name']} vient de répondre à la question 1 sur son socle familial : '{user_message}'. "
            f"Rédige une transition de 2 phrases maximum en **mode humoristique/cynique**. Fais une blague sur sa réponse, puis enchaîne **doucement** avec la question 2 sans rupture. "
            f"Question 2 : {DIAGNOSTIC_QUESTIONS['q2_geo']}"
        )
        response = await chat_with_ai(profile, [{"role": "user", "content": transition_prompt}], context)
        await update.message.reply_text(response)
        return
    
    # === PROTOCOLE D'ACCUEIL GUIDÉ (Q2 Géographie/Ancrage) ===
    elif state == "awaiting_context_q2_geo":
        profile["geo_info"] = user_message # Enregistrement
        context.user_data["state"] = "awaiting_context_q3_pro" # Nouvelle Q3
        # IA génère la transition (Validation Humour + Question 3)
        transition_prompt = (
            f"L'utilisateur {profile['name']} vient de répondre à la question 2 sur son lieu de vie : '{user_message}'. "
            f"Rédige une transition de 2 phrases maximum en **mode humoristique/cynique**. Fais une blague sur sa réponse, puis enchaîne **doucement** avec la question 3 sans rupture. "
            f"Question 3 : {DIAGNOSTIC_QUESTIONS['q3_pro']}"
        )
        response = await chat_with_ai(profile, [{"role": "user", "content": transition_prompt}], context)
        await update.message.reply_text(response)
        return

    # === PROTOCOLE D'ACCUEIL GUIDÉ (Q3 Professionnel/Social) ===
    elif state == "awaiting_context_q3_pro":
        profile["pro_info"] = user_message # Enregistrement
        context.user_data["state"] = "chatting" # Fin de l'accueil
        # Message de clôture généré par l'IA
        closing_prompt = (
            f"L'utilisateur {profile['name']} a terminé le diagnostic en répondant : '{user_message}'. "
            f"Rédige un message final de 3-4 phrases qui **valide sa fiche psy avec une punchline cynique**, et l'invite à se confier sur ce qui le préoccupe, en utilisant son prénom."
        )
        response = await chat_with_ai(profile, [{"role": "user", "content": closing_prompt}], context)
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
        raw_resp = await asyncio.to_thread(call_model_api_sync, payload_messages, 0.85, 700) # MAX_TOKENS AUGMENTÉ

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
            clean_resp = clean_resp + f"\n\n(Désolée {profile['name']}, je me suis répété, c'est l'âge de mes serveurs. Peux-tu reformuler pour voir si mon cerveau marche ?)"

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

    logger.info("Soph_IA V68 starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
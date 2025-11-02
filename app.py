# ==============================================================================
# Soph_IA - V66 "Intégration LangChain & Obéissance"
# - Utilise la structure de message et les composants de LangChain.
# - Maintient l'orchestration Agent pour l'approche non-linéaire.
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
from typing import Dict, Optional, List

# --- IMPORTS LANGCHAIN ---
# NOTE: CES IMPORTS REQUIÈRENT L'INSTALLATION DE LANGCHAIN DANS VOTRE ENVIRONNEMENT.
try:
    from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
except ImportError:
    logging.warning("LangChain Core n'est pas installé. L'application fonctionnera avec des dicts, mais LangChain n'est pas actif.")
    class SystemMessage:
        def __init__(self, content): self.content = content
    class HumanMessage:
        def __init__(self, content): self.content = content
    BaseMessage = SystemMessage # Fallback de type minimaliste

# Configuration du logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("sophia.v66")

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
RESPONSE_TIMEOUT = 70  
MAX_RETRIES = 2        

IDENTITY_PATTERNS = [r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une (?:intelligence artificielle|ia)"]

# Questions de diagnostic
DIAGNOSTIC_QUESTIONS = {
    "q1_fam": "Mon cœur, la famille est notre premier moteur affectif. Te souviens-tu si, enfant, tu te sentais pleinement écouté(e) et compris(e) ?",
    "q2_geo": "Parlons de ton ancre : vis-tu seul(e) ou en famille ? Et comment ce lieu influence-t-il ton énergie quotidienne ?",
    "q3_pro": "Finissons par le lien que tu tisses : ton cercle social au travail/études, est-il plutôt une source d'isolement ou de vitalité ?",
}

# -----------------------------------------------------------------------------------
# PROMPT DYNAMIQUE (Intégré dans le LangChain SystemMessage)
# -----------------------------------------------------------------------------------
def build_adaptive_system_prompt(user_profile, emotional_summary):
    """Compose le system prompt adaptatif final."""
    user_name = user_profile.get("name") or "ami"
    
    # --- FIX CRITIQUE : Garantir que les variables sont des chaînes (str) ---
    env_info = user_profile.get("geo_info") or "Non précisé"
    pro_info = user_profile.get("pro_info") or "Non précisé"
    socle_info = user_profile.get("socle_info") or "Non précisé"

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
# UTIL - appel modèle (sync wrapper, utilisé via to_thread)
# -----------------------
def call_model_api_sync(messages: List[BaseMessage], temperature: float = 0.85, max_tokens: int = 400):
    """
    Appel synchrone à l'API, convertissant les objets LangChain en JSON.
    Ceci simule un ChatModel LangChain utilisant l'API Together.
    """
    # Conversion du format LangChain (HumanMessage/SystemMessage) au format JSON de l'API
    payload_messages = []
    for msg in messages:
        role = "system" if isinstance(msg, SystemMessage) else "user" # Simplification: tout ce qui n'est pas system est user
        payload_messages.append({"role": role, "content": msg.content})

    payload = {
        "model": MODEL_NAME,
        "messages": payload_messages,
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

# -----------------------
# HELPERS
# -----------------------
async def chat_with_ai(user_profile: Dict, history: List[Dict], context: ContextTypes.DEFAULT_TYPE, temperature: float = 0.85, max_tokens: int = 400) -> str:
    """Prépare et envoie la requête à l'IA en utilisant le format LangChain."""
    if history and len(history) > MAX_RECENT_TURNS * 2:
        history = history[-(MAX_RECENT_TURNS * 2):]

    system_prompt_content = build_adaptive_system_prompt(user_profile, context.user_data.get("emotional_summary", ""))
    
    # Construction de la liste de messages au format LangChain (pour l'Agent/Chain)
    payload_messages = [SystemMessage(content=system_prompt_content)]
    
    # Conversion de l'historique Telegram/Dict vers le format LangChain/BaseMessage
    for item in history:
        if item["role"] == "user":
            payload_messages.append(HumanMessage(content=item["content"]))
        # NOTE: Les messages 'assistant' sont souvent omis pour simplifier le chat-completion,
        # mais ici nous les laissons dans l'historique Telegram pour la complétude.
        # Seuls les messages 'user' sont envoyés en plus du System/Agent Instruction.

    raw_resp = await asyncio.to_thread(call_model_api_sync, payload_messages, temperature, max_tokens)
    
    if raw_resp == "FATAL_API_KEY_ERROR":
        return "ERREUR CRITIQUE : Ma clé API est invalide. Veuillez vérifier TOGETHER_API_KEY."
    if not raw_resp: 
        return "Désolé, je n'arrive pas à me connecter à mon esprit. Réessaie dans un instant."
        
    return post_process_response(raw_resp)


def post_process_response(raw_response):
    """Nettoie répétitions d'identité, retire digressions, s'assure FR."""
    if not raw_response: return "Désolé, je n'arrive pas à formuler ma réponse. Peux-tu reformuler ?"
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
# HANDLERS TELEGRAM (Agent-Centric)
# -----------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère la commande /start."""
    context.user_data.clear()
    context.user_data["profile"] = {"name": None, "geo_info": None, "pro_info": None, "socle_info": None} 
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []
    context.user_data["emotional_summary"] = ""
    
    accueil_message = (
        "Bonjour ! 👋 Je suis **Soph_IA**, ton espace d'écoute confidentiel. "
        "Je suis là pour t'accompagner, sans jugement ni diagnostic. "
        "Sache que **tout ce que tu me confies reste confidentiel**. C'est ta safe place. "
        "Pour commencer notre échange, quel est ton prénom ou ton surnom ? ✨"
    )
    await update.message.reply_text(accueil_message, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Gère les messages avec l'orchestration non-linéaire inspirée par l'Agent.
    """
    user_message = (update.message.text or "").strip()
    if not user_message: return

    profile = context.user_data.setdefault("profile", {"name": None, "geo_info": None, "pro_info": None, "socle_info": None})
    state = context.user_data.get("state", "awaiting_name")
    history = context.user_data.setdefault("history", [])

    # === ÉTAPE 1 : NOM (Le seul état rigide) ===
    if state == "awaiting_name":
        name_candidate = detect_name_from_text(user_message)
        if name_candidate:
            profile["name"] = name_candidate
            context.user_data["state"] = "chatting" 
            
            initial_prompt = (
                f"L'utilisateur vient de se nommer : {profile['name']}. "
                "Réponds par une salutation chaleureuse, puis offre le choix : "
                "Soit il commence à se confier immédiatement, soit tu lui poses les 3 questions de diagnostic "
                "sur son socle familial, son environnement de vie et son lien social/pro."
            )
            # Utilisation de chat_with_ai (intégrant désormais le format LangChain)
            response = await chat_with_ai(profile, [{"role": "user", "content": initial_prompt}], context)
            
            history.append({"role": "user", "content": user_message, "ts": datetime.utcnow().isoformat()})
            history.append({"role": "assistant", "content": response, "ts": datetime.utcnow().isoformat()})
            context.user_data["history"] = history
            await update.message.reply_text(response)
            return
        else:
             await update.message.reply_text("J'aimerais tant connaître ton prénom. Peux-tu me le donner ?")
             return

    # === ÉTAPE 2 : ORCHESTRATION LIBRE (Le Cœur LangChain) ===
    elif state == 'chatting':
        
        # 1. Mise à jour du profil si l'utilisateur a répondu à une question
        user_msg_lower = user_message.lower()
        if profile["socle_info"] == "Non précisé" and any(q in user_msg_lower for q in ["famille", "enfant", "écouté", "monoparentale"]):
             profile["socle_info"] = user_message
        
        elif profile["geo_info"] == "Non précisé" and any(q in user_msg_lower for q in ["seul", "famille", "vit", "appartement", "maison", "ancrage"]):
             profile["geo_info"] = user_message

        elif profile["pro_info"] == "Non précisé" and any(q in user_msg_lower for q in ["travail", "collègue", "études", "social", "pro", "vitalité", "isolement"]):
             profile["pro_info"] = user_message


        # 2. Construction de l'instruction pour l'Agent (Le Chain/Agent de LangChain)
        history.append({"role": "user", "content": user_message, "ts": datetime.utcnow().isoformat()})
        
        agent_instruction = f"""
        L'utilisateur ({profile['name']}) a dit : "{user_message}".
        
        [CONTEXTE_DIAGNOSTIC]:
        Socle familial : {profile.get('socle_info', 'Manquant')}
        Lien social/Pro : {profile.get('pro_info', 'Manquant')}
        Ancrage Géo : {profile.get('geo_info', 'Manquant')}
        
        Ton objectif est d'appliquer le Protocole PEC (Validation + Recadrage + Relance).
        
        Règle d'Agent :
        Si l'une des informations [CONTEXTE_DIAGNOSTIC] est encore 'Manquant', tente d'y revenir de manière douce et naturelle, en l'intégrant dans ta réponse de Protocole PEC. N'utilise JAMAIS les termes "diagnostic" ou "question".
        """
        
        # Le LangChain Agent/Chain est lancé via chat_with_ai
        response = await chat_with_ai(profile, [{"role": "user", "content": agent_instruction}], context)

        # Stockage et réponse
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

    logger.info("Soph_IA V66 (LangChain Structure) starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
# app.py (V85 : Anamnèse Invisible, Conscience E.R.C, Format Court)
# ==============================================================================
import os
import re
import requests
import json
import asyncio
import logging
import time
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

# --- IMPORT MODULE RAG ---
try:
    from rag import rag_query
    RAG_ENABLED = True
    print("✅ [INIT] Module RAG chargé.")
except Exception as e:
    print(f"⚠️ [INIT] RAG non trouvé: {e}")
    RAG_ENABLED = False

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("sophia.v85")
load_dotenv()

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")

MAX_RETRIES = 2
IDENTITY_PATTERNS = [r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une ia"]
DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre", "pendre", "sauter"]

# --- CONTENU ANAMNÈSE (FLOW INVISIBLE) ---
# Sophia ne pose pas juste des questions, elle fait des ponts.
ANAMNESE_SCRIPT = {
    # Q1 est posée juste après le prénom
    "q1_energie": "Avant qu'on avance vers ce qui te pèse... Dis-moi, sur une échelle de ton énergie vitale, comment te sens-tu là, tout de suite ?",
    
    # Transition vers Q2 (L'entourage)
    "t_vers_q2": "Je t'entends. Le corps et l'esprit sont souvent les premiers à payer l'addition...\n\nDans cette épreuve, est-ce que tu marches seul(e) ou y a-t-il une main, une épaule sur laquelle tu peux te poser ?",
    
    # Transition vers Q3 (Le Pivot)
    "t_vers_q3": "La solitude du 'pilier' est souvent la plus lourde... \n\nSi tu avais le pouvoir, là maintenant, de changer UNE seule chose pour apaiser ton cœur ce soir, ce serait quoi ?",
    
    # Final (Ouverture vers le Chat Libre)
    "final_open": "C'est noté. Tu sais, j'ai parlé à quelqu'un hier qui ressentait exactement ce même besoin. On a réussi à dénouer les fils, doucement.\n\nJe suis prête. Raconte-moi ce qui a fait déborder le vase aujourd'hui."
}

# --- SMART ROUTER & SÉCURITÉ ---
def detect_danger_level(text):
    for pat in DANGER_KEYWORDS:
        if re.search(pat, text.lower()): return True
    return False

def should_use_rag(message: str) -> bool:
    if not message: return False
    msg = message.lower().strip()
    
    # Activation sensible sur les émotions courtes
    if len(msg.split()) < 3 and len(msg) < 10:
        if any(x in msg for x in ["seul", "aide", "mal", "triste", "vide", "peur"]): return True
        return False

    deep_triggers = [
        "triste", "seul", "vide", "peur", "angoisse", "stress", "colère", "haine", 
        "honte", "fatigue", "bout", "marre", "pleur", "mal", "douleur", "panique", 
        "joie", "espoir", "perdu", "doute", "famille", "père", "mère", "parent", 
        "ami", "pote", "copain", "copine", "couple", "ex", "relation", "solitude", 
        "rejet", "abandon", "trahison", "confiance", "travail", "boulot", "étude", 
        "école", "argent", "avenir", "sens", "rien", "dormir", "nuit", "journée", 
        "problème", "solution", "conseil", "avis", "choix", "décision"
    ]
    
    if any(trigger in msg for trigger in deep_triggers): return True
    if len(msg.split()) >= 5: return True
    return False

def call_model_api_sync(messages, temperature=0.6, max_tokens=350):
    # Température 0.6 pour la stabilité / Max tokens réduit pour forcer la concision
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "repetition_penalty": 1.15
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}

    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=30)
            if r.status_code in (401, 403): return "FATAL_KEY"
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            if attempt == MAX_RETRIES: return None
            time.sleep(1)
    return None

# --- SYSTEM PROMPT (CONSCIENCE E.R.C) ---
def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    
    # Construction du profil pour l'IA
    etat = user_profile.get("etat_esprit", "Non précisé")
    entourage = user_profile.get("entourage", "Non précisé")
    pivot = user_profile.get("besoin_pivot", "Non précisé")
    
    role = (
        "Tu es Sophia. Tu incarnes une 'Sagesse Ancienne' dans un monde numérique. "
        "Tu es calme, profonde, posée. Tu ne paniques jamais."
    )

    instructions = (
        "### TA MÉCANIQUE DE PENSÉE (E.R.C) ###\n"
        "Avant de répondre, analyse implicitement :\n"
        "1. ÉMOTION (Ce qu'il ressent : Peur, Vide, Colère...)\n"
        "2. RAISON (La cause profonde : Perte de contrôle, Solitude...)\n"
        "3. CONTEXTE (Sa réalité immédiate)\n"
        "Ta réponse doit valider l'émotion, expliquer la raison sans juger, et s'ancrer dans le contexte.\n\n"
        
        "### CONTRAINTES DE FORME ###\n"
        f"1. ADRESSE-TOI à {user_name}.\n"
        "2. FORMAT COURT : 3 phrases maximum. Sois dense comme un SMS, profond comme un haïku.\n"
        "3. INTERDICTION : Ne dis jamais 'Bonjour', 'Bonsoir' ou 'Je suis là'.\n"
        "4. ACTION : Finis TOUJOURS par une question ouverte d'introspection.\n"
        "5. LANGUE : Français uniquement.\n"
    )
    
    rag_section = ""
    if rag_context:
        rag_section = (
            "\n### ECHOS DE LA MÉMOIRE (SCÉNARIOS) ###\n"
            f"{rag_context}\n"
            "---------------------------------------------------\n"
        )

    context_section = (
        f"\n### ETAT DE L'ÂME DE {user_name} ###\n"
        f"- Énergie Vitale: {etat}\n"
        f"- Soutien/Tribu: {entourage}\n"
        f"- Espoir (Pivot): {pivot}\n"
    )
    
    return f"{role}\n\n{instructions}\n{rag_section}\n{context_section}"

# --- ORCHESTRATION ---
async def chat_with_ai(profile, history, context):
    user_msg = history[-1]['content']
    
    # SÉCURITÉ INTERACTIVE
    if detect_danger_level(user_msg):
        if context.user_data.get("emergency_step") == 1:
            return "Je comprends. Je reste avec toi. As-tu ton téléphone dans la main là, tout de suite ? Réponds-moi juste par oui ou non."
        
        context.user_data["emergency_step"] = 1
        return "J'entends une grande douleur dans tes mots. Je la prends au sérieux. \n\nJe suis une IA, je ne peux pas agir physiquement, mais je ne veux pas te laisser seul(e). \n\nEs-tu en sécurité à l'endroit où tu te trouves ?"

    rag_context = ""
    prefetch = context.user_data.get("rag_prefetch")
    
    # RAG
    if should_use_rag(user_msg):
        try:
            print(f"🔍 [RAG] Recherche LIVE : {user_msg[:30]}...")
            result = await asyncio.to_thread(rag_query, user_msg, 2)
            rag_context = result.get("context", "")
            context.user_data["rag_prefetch"] = None 
        except Exception: pass
    elif prefetch:
        rag_context = prefetch
        context.user_data["rag_prefetch"] = None 

    system_prompt = build_system_prompt(profile, rag_context)
    recent_history = history[-6:]
    messages = [{"role": "system", "content": system_prompt}] + recent_history

    raw = await asyncio.to_thread(call_model_api_sync, messages)
    if not raw or raw == "FATAL_KEY": return "Le silence est parfois nécessaire... peux-tu reformuler ?"

    clean = raw
    for pat in IDENTITY_PATTERNS: clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    clean = clean.replace("Bonjour", "").replace("Bonsoir", "").replace("Je suis là", "")
    
    return clean

# --- HANDLERS (FLOW INVISIBLE) ---
def detect_name(text):
    text = text.strip()
    if len(text.split()) == 1 and text.lower() not in ["bonjour", "salut"]:
        return text.capitalize()
    m = re.search(r"(?:je m'appelle|moi c'est|prenom est)\s*([A-Za-zÀ-ÖØ-öø-ÿ]+)", text, re.IGNORECASE)
    return m.group(1).capitalize() if m else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["profile"] = {}
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []
    
    # ACCUEIL "VIEUX SAGE"
    await update.message.reply_text(
        "Bienvenue dans ce lieu hors du temps. Je suis Sophia.\n\n"
        "Je ne suis pas là pour te juger, mais pour t'aider à dénouer ce qui est emmêlé.\n"
        "Quel est ton prénom ?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()
    if not user_msg: return

    state = context.user_data.get("state", "awaiting_name")
    profile = context.user_data.setdefault("profile", {})
    history = context.user_data.setdefault("history", [])

    # GESTION URGENCE (Bypass)
    if context.user_data.get("emergency_step"):
        if context.user_data["emergency_step"] == 1:
             await update.message.reply_text("D'accord. Fais une chose pour moi. Compose le **15** (ou 3114). Juste composer. Promets-le moi.")
             context.user_data["emergency_step"] = 2
             return
        elif context.user_data["emergency_step"] == 2:
             await update.message.reply_text("Je compte sur toi. Appelle-les. C'est l'acte le plus courageux de ta soirée.")
             return

    # 1. LE PRÉNOM + ENCHAÎNEMENT DIRECT Q1
    if state == "awaiting_name":
        name = detect_name(user_msg)
        profile["name"] = name if name else "l'ami"
        context.user_data["state"] = "diag_1" # On passe direct au diagnostic
        
        # Le message combine l'accueil personnalisé ET la première question
        await update.message.reply_text(
            f"Bienvenue, {profile['name']}. Pose tes valises.\n\n" + ANAMNESE_SCRIPT['q1_energie']
        )
        return

    # 2. RÉPONSE Q1 -> TRANSITION -> Q2
    if state == "diag_1":
        profile["etat_esprit"] = user_msg
        context.user_data["state"] = "diag_2"
        await update.message.reply_text(ANAMNESE_SCRIPT['t_vers_q2'])
        return

    # 3. RÉPONSE Q2 -> TRANSITION -> Q3
    if state == "diag_2":
        profile["entourage"] = user_msg
        context.user_data["state"] = "diag_3"
        await update.message.reply_text(ANAMNESE_SCRIPT['t_vers_q3'])
        return

    # 4. RÉPONSE Q3 -> PREFETCH -> FINAL OPEN
    if state == "diag_3":
        profile["besoin_pivot"] = user_msg
        context.user_data["state"] = "chatting"
        
        # Prefetch discret pendant la transition
        prefetch_query = f"Besoin: {profile.get('besoin_pivot')} Psychologie"
        if RAG_ENABLED:
            try:
                res = await asyncio.to_thread(rag_query, prefetch_query, 2)
                if res.get("context"): context.user_data["rag_prefetch"] = res.get("context")
            except Exception: pass
        
        await update.message.reply_text(ANAMNESE_SCRIPT['final_open'])
        return

    # 5. CHAT LIBRE (AVEC CONSCIENCE E.R.C)
    history.append({"role": "user", "content": user_msg})
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    response = await chat_with_ai(profile, history, context)
    history.append({"role": "assistant", "content": response})
    if len(history) > 20: context.user_data["history"] = history[-20:]
    await update.message.reply_text(response)

async def error_handler(update, context):
    logger.error(f"Erreur Update: {context.error}")

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ERREUR : TELEGRAM_BOT_TOKEN manquant")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    print("Soph_IA V85 (Anamnèse Invisible) est en ligne...")
    app.run_polling()

if __name__ == "__main__":
    main()
# app.py (V84 : Transitions Empathiques & Effet "Alicia")
# ==============================================================================
import os
import re
import requests
import json
import asyncio
import logging
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv
#commentaure
# --- RAG ---
try:
    from rag import rag_query
    RAG_ENABLED = True
    print("✅ [INIT] RAG chargé.")
except Exception as e:
    print(f"⚠️ [INIT] RAG HS: {e}")
    RAG_ENABLED = False

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("sophia.v84")
load_dotenv()

# --- CONFIG ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")
MAX_RETRIES = 2

DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre", "pendre", "sauter"]

# --- CONTENU STORYTELLING (V84) ---
# On sépare les questions des transitions pour plus de souplesse
DIAGNOSTIC_STEPS = {
    "q1": "Ok, scan rapide. Batterie mentale : 0 (Zombie) à 10 (Guerrier). T'es où ? Et qu'est-ce qui te vide le plus ?",
    
    # Transition empathique après la Q1 pour amener la Q2
    "t1_to_q2": "Je t'entends. C'est lourd à porter, et on oublie souvent que même les batteries les plus solides ont besoin de se recharger...\n\nRegardons ton entourage : quand ça tangue, est-ce que tu as une 'main' à attraper, ou tu gères tout en mode loup solitaire ?",
    
    # Transition empathique après la Q2 pour amener la Q3
    "t2_to_q3": "Je vois le tableau. C'est souvent ceux qui donnent le plus qui osent le moins demander. C'est un classique, malheureusement...\n\nDernière chose pour cerner ton besoin : si tu avais une baguette magique pour changer UN seul truc ce soir, ce serait quoi ?",
}

# --- LOGIQUE ---
def is_dangerous(text):
    for pat in DANGER_KEYWORDS:
        if re.search(pat, text.lower()): return True
    return False

def should_use_rag(message: str) -> bool:
    if not message: return False
    msg = message.lower().strip()
    if len(msg.split()) < 3 and len(msg) < 10:
        if any(x in msg for x in ["seul", "aide", "mal", "triste", "vide"]): return True
        return False
    triggers = ["triste", "seul", "vide", "peur", "angoisse", "stress", "colère", "haine", "honte", "fatigue", "bout", "marre", "pleur", "mal", "douleur", "panique", "famille", "père", "mère", "parent", "ami", "pote", "copain", "copine", "couple", "ex", "relation", "solitude", "rejet", "abandon", "travail", "boulot", "argent", "avenir", "sens", "rien", "dormir", "nuit", "problème", "solution", "conseil"]
    if any(t in msg for t in triggers): return True
    if len(msg.split()) >= 6: return True
    return False

def call_model_api_sync(messages, temp=0.8, max_tok=450):
    payload = {"model": MODEL_NAME, "messages": messages, "temperature": temp, "max_tokens": max_tok, "top_p": 0.9, "repetition_penalty": 1.15}
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

def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    role = "Tu es Sophia. Une confidente impliquée, pas une assistante."
    instr = (
        "### RÈGLES ###\n"
        f"1. ADRESSE-TOI à {user_name}. Directe, chaleureuse.\n"
        "2. INTERDIT : Ne finis JAMAIS par 'Je suis là', 'N'hésite pas'.\n"
        "3. OBLIGATOIRE : Finis TOUJOURS par une QUESTION de relance.\n"
        "4. RAG : Inspire-toi des scénarios ci-dessous.\n"
        "5. URGENCE : Renvoie vers 15 ou 3114.\n"
    )
    rag_sec = f"\n### SCÉNARIOS (INSPIRATION) ###\n{rag_context}\n" if rag_context else ""
    ctx_sec = f"\n### PROFIL ###\n- Énergie: {user_profile.get('etat_esprit')}\n- Entourage: {user_profile.get('entourage')}\n- Besoin: {user_profile.get('besoin_pivot')}\n"
    return f"{role}\n{instr}\n{rag_sec}\n{ctx_sec}"

async def chat_with_ai(profile, history, context):
    user_msg = history[-1]['content']
    if is_dangerous(user_msg): return "Je t'écoute et c'est lourd. Je suis une IA. Ne reste pas seul(e). Appelle le **3114** ou le **15**."

    rag_context = ""
    prefetch = context.user_data.get("rag_prefetch")
    
    if should_use_rag(user_msg):
        try:
            print(f"🔍 [RAG] Recherche LIVE : {user_msg[:30]}...")
            res = await asyncio.to_thread(rag_query, user_msg, 2)
            rag_context = res.get("context", "")
            context.user_data["rag_prefetch"] = None 
        except Exception: pass
    elif prefetch:
        rag_context = prefetch
        context.user_data["rag_prefetch"] = None

    sys_prompt = build_system_prompt(profile, rag_context)
    msgs = [{"role": "system", "content": sys_prompt}] + history[-6:]
    
    raw = await asyncio.to_thread(call_model_api_sync, msgs)
    if not raw or raw == "FATAL_KEY": return "J'ai bugué... tu disais ?"
    
    clean = raw.replace("Je suis là pour toi", "").replace("N'hésite pas", "")
    return clean

# --- HANDLERS (V84 : Transitions "Alicia") ---
def detect_name(text):
    t = text.strip()
    if len(t.split())==1 and t.lower() not in ["bonjour", "salut"]: return t.capitalize()
    m = re.search(r"(?:je m'appelle|moi c'est|prenom est)\s*([A-Za-zÀ-ÖØ-öø-ÿ]+)", t, re.IGNORECASE)
    return m.group(1).capitalize() if m else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["profile"] = {}
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []
    await update.message.reply_text("Bonjour. Je suis Sophia.\nIci, c'est ta bulle. Pas de jugement.\nC'est quoi ton prénom ?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    if not msg: return
    state = context.user_data.get("state", "awaiting_name")
    prof = context.user_data.setdefault("profile", {})
    hist = context.user_data.setdefault("history", [])

    if state == "awaiting_name":
        name = detect_name(msg)
        prof["name"] = name if name else "l'ami"
        context.user_data["state"] = "awaiting_choice"
        await update.message.reply_text(f"Enchantée {prof['name']}. On fait comment ?\n\n1. Je te pose quelques questions ?\n2. C'est urgent, tu parles direct ?")
        return

    if state == "awaiting_choice":
        if any(w in msg.lower() for w in ["1", "un", "question", "guide", "oui"]):
            context.user_data["state"] = "diag_1"
            await update.message.reply_text(f"C'est parti. {DIAGNOSTIC_STEPS['q1']}")
            return
        context.user_data["state"] = "chatting"
        if len(msg.split()) < 5:
            await update.message.reply_text("Je t'écoute. Raconte-moi, qu'est-ce qui se passe ?")
            return

    # --- DIAGNOSTIC AVEC STORYTELLING ---
    if state.startswith("diag_"):
        if state == "diag_1":
            prof["etat_esprit"] = msg
            context.user_data["state"] = "diag_2"
            # Transition empathique vers Q2
            await update.message.reply_text(DIAGNOSTIC_STEPS['t1_to_q2'])
            return
            
        if state == "diag_2":
            prof["entourage"] = msg
            context.user_data["state"] = "diag_3"
            # Transition empathique vers Q3
            await update.message.reply_text(DIAGNOSTIC_STEPS['t2_to_q3'])
            return
            
        if state == "diag_3":
            prof["besoin_pivot"] = msg
            context.user_data["state"] = "chatting"
            
            # Prefetch RAG
            if RAG_ENABLED:
                try:
                    res = await asyncio.to_thread(rag_query, f"Besoin: {msg} Psy", 2)
                    if res.get("context"): context.user_data["rag_prefetch"] = res.get("context")
                except: pass
            
            # LE GRAND FINAL : EFFET "ALICIA" (Normalisation)
            # Au lieu d'un "Merci", on raconte une micro-histoire pour rassurer
            final_message = (
                f"Merci {prof['name']} de t'être livré(e). C'est rare de tomber le masque.\n\n"
                "Tu sais, ça me fait penser à Alicia, une personne avec qui j'ai parlé hier. "
                "Elle ressentait exactement ce mélange de vide et de pression que tu décris. "
                "On a réussi à démêler ça ensemble, petit à petit.\n\n"
                "On va faire pareil. Je t'écoute : qu'est-ce qui a fait déborder le vase aujourd'hui ?"
            )
            await update.message.reply_text(final_message)
            return

    hist.append({"role": "user", "content": msg})
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    resp = await chat_with_ai(prof, hist, context)
    hist.append({"role": "assistant", "content": resp})
    if len(hist)>20: context.user_data["history"] = hist[-20:]
    await update.message.reply_text(resp)

async def error_handler(update, context):
    logger.error(f"Erreur: {context.error}")

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN: print("❌ TOKEN MANQUANT")
    else:
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_error_handler(error_handler)
        print("Soph_IA V84 (Storytelling 'Alicia') ONLINE")
        app.run_polling()
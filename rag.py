import os
import chromadb
import requests
from dotenv import load_dotenv

load_dotenv()

# -------------------------
# CONFIGURATION
# -------------------------
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY")
CHROMA_TENANT = os.getenv("CHROMA_TENANT")
CHROMA_DATABASE = os.getenv("CHROMA_DATABASE", "sophia-arbre")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "sophia")

# On a besoin de ces clés pour garantir que la question est vectorisée
# exactement comme les données ont été ingérées.
HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
HF_MODEL_URL = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"

_CLIENT = None
_COLLECTION = None

# --- CLASSE D'EMBEDDING PERSONNALISÉE (CRITIQUE) ---
# Cette classe force Chroma à utiliser l'API HuggingFace au lieu du modèle local par défaut.
class HuggingFaceEmbeddingFunction(chromadb.EmbeddingFunction):
    def __call__(self, input: list[str]) -> list[list[float]]:
        if not HF_API_KEY:
            print("⚠️ [RAG] Clé HF manquante. Impossible de vectoriser.")
            return []
        
        headers = {"Authorization": f"Bearer {HF_API_KEY}"}
        try:
            # On ajoute wait_for_model pour éviter les erreurs si l'API dort
            resp = requests.post(
                HF_MODEL_URL, 
                headers=headers, 
                json={"inputs": input, "options": {"wait_for_model": True}}, 
                timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"⚠️ [RAG] Erreur Embeddings HF: {e}")
            return []

def get_collection():
    global _CLIENT, _COLLECTION
    if _COLLECTION: return _COLLECTION

    if not CHROMA_API_KEY or not CHROMA_TENANT:
        print("❌ [RAG] Erreur: Clés API Chroma manquantes.")
        return None

    try:
        print(f"🔌 [RAG] Connexion à la collection '{CHROMA_COLLECTION_NAME}'...")
        _CLIENT = chromadb.CloudClient(
            api_key=CHROMA_API_KEY,
            tenant=CHROMA_TENANT,
            database=CHROMA_DATABASE,
        )
        
        # On instancie notre fonction d'embedding spécifique
        emb_fn = HuggingFaceEmbeddingFunction() if HF_API_KEY else None

        # On injecte la fonction dans la récupération de la collection
        if emb_fn:
            _COLLECTION = _CLIENT.get_collection(name=CHROMA_COLLECTION_NAME, embedding_function=emb_fn)
        else:
            # Fallback (déconseillé si ingestion faite avec HF)
            print("⚠️ [RAG] Attention: Utilisation embedding par défaut (risque d'incompatibilité).")
            _COLLECTION = _CLIENT.get_collection(name=CHROMA_COLLECTION_NAME)
            
        print("✅ [RAG] Collection connectée avec succès.")
        return _COLLECTION
    except Exception as e:
        print(f"❌ [RAG] Erreur connexion: {e}")
        return None

def rag_query(user_message: str, k: int = 2):
    """Récupère les scénarios similaires dans la base de données."""
    collection = get_collection()
    if not collection: return {"context": "", "chunks": [], "metadatas": []}

    try:
        # Chroma va utiliser emb_fn défini plus haut pour vectoriser 'user_message'
        results = collection.query(
            query_texts=[user_message],
            n_results=k,
        )
        
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        if not documents: return {"context": "", "chunks": [], "metadatas": []}

        context_blocks = []
        for meta in metadatas:
            meta = meta or {}
            block = (
                f"--- SCÉNARIO (Thème: {meta.get('theme', 'Général')}) ---\n"
                f"👤 Situation: \"{meta.get('question', 'Inconnue')}\"\n"
                f"💡 Réponse Psy: \"{meta.get('reponse', 'Non disponible')}\"\n"
            )
            # Gestion explicite du Redflag pour alerter app.py
            is_redflag = str(meta.get('redflag')).lower() in ["oui", "true", "yes", "1"]
            if is_redflag:
                block += "⚠️ NOTE: Redflag DÉTECTÉ (Situation à risque)\n"
                
            context_blocks.append(block)

        return {
            "context": "\n".join(context_blocks),
            "chunks": documents,
            "metadatas": metadatas
        }
    except Exception as e:
        print(f"⚠️ [RAG] Erreur requête: {e}")
        return {"context": "", "chunks": [], "metadatas": []}
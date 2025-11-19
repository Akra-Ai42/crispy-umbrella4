import os
import chromadb
import requests
from dotenv import load_dotenv

load_dotenv()

# -------------------------
# CONFIGURATION (Ton ancienne base)
# -------------------------
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY")
CHROMA_TENANT = os.getenv("CHROMA_TENANT")

# Tes paramètres exacts :
CHROMA_DATABASE = "sophia-arbre" 
CHROMA_COLLECTION_NAME = "sophia" 

# Clé Hugging Face (Indispensable pour ne pas crasher sur Render)
HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
# Ce modèle API est mathématiquement identique à ton modèle local
HF_MODEL_URL = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"

_CLIENT = None
_COLLECTION = None

# --- CLASSE MAGIQUE (Compatibilité 100% sans RAM) ---
class HuggingFaceEmbeddingFunction(chromadb.EmbeddingFunction):
    def __call__(self, input: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {HF_API_KEY}"}
        try:
            # On demande à HF de calculer comme "all-MiniLM-L6-v2"
            response = requests.post(HF_MODEL_URL, headers=headers, json={"inputs": input, "options":{"wait_for_model":True}}, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"⚠️ Erreur API: {e}")
            return []

def get_collection():
    global _CLIENT, _COLLECTION
    if _COLLECTION: return _COLLECTION

    try:
        print(f"🔌 Connexion RAG à '{CHROMA_DATABASE}/{CHROMA_COLLECTION_NAME}'...")
        _CLIENT = chromadb.CloudClient(
            api_key=CHROMA_API_KEY,
            tenant=CHROMA_TENANT,
            database=CHROMA_DATABASE,
        )
        
        # On utilise l'API pour générer les mêmes vecteurs que ton PC
        emb_fn = HuggingFaceEmbeddingFunction()
        
        _COLLECTION = _CLIENT.get_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=emb_fn
        )
        print("✅ RAG Connecté (Base Existante).")
        return _COLLECTION
    except Exception as e:
        print(f"❌ Erreur connexion RAG: {e}")
        return None

def rag_query(user_message: str, n_results: int = 3):
    collection = get_collection()
    if not collection: return {"context": "", "chunks": []}

    try:
        results = collection.query(
            query_texts=[user_message],
            n_results=n_results,
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        
        context_blocks = []
        for meta in metadatas:
            meta = meta or {}
            # Adaptation à tes noms de colonnes (question/reponse ou Q/J)
            q = meta.get('question') or meta.get('Q') or "N/A"
            j = meta.get('reponse') or meta.get('J') or "N/A"
            
            block = (
                f"--- CAS SIMILAIRE ---\n"
                f"Situation: \"{q}\"\n"
                f"Conseil Sage: \"{j}\""
            )
            context_blocks.append(block)

        full_context = "\n\n".join(context_blocks)
        return {"context": full_context, "chunks": documents}

    except Exception as e:
        print(f"⚠️ Erreur Query: {e}")
        return {"context": "", "chunks": []}
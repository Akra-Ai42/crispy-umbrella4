# rag.py
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

# Paramètres
CHROMA_DATABASE = os.getenv("CHROMA_DATABASE", "sophia-arbre")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "sophia")

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY")  # facultatif, utilisé si besoin pour embeddings via HF
HF_MODEL_URL = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"

_CLIENT = None
_COLLECTION = None

# --- EmbeddingFunction optionnelle (compatible Chroma Cloud) ---
class HuggingFaceEmbeddingFunction(chromadb.EmbeddingFunction):
    def __call__(self, input: list[str]) -> list[list[float]]:
        if not HF_API_KEY:
            # Si pas de clé HF, nous retournons une liste vide : Chroma Cloud utilisera ses propres embeddings
            print("⚠️ HF_API_KEY missing — skipping HF embedding call; rely on Chroma internal embeddings.")
            return []
        headers = {"Authorization": f"Bearer {HF_API_KEY}"}
        try:
            resp = requests.post(HF_MODEL_URL, headers=headers, json={"inputs": input, "options": {"wait_for_model": True}}, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"⚠️ HuggingFace embedding error: {e}")
            return []

def get_collection():
    """Connect to Chroma Cloud and return the collection. Cache client/collection."""
    global _CLIENT, _COLLECTION
    if _COLLECTION:
        return _COLLECTION

    try:
        print(f"🔌 Connecting to Chroma Cloud: database='{CHROMA_DATABASE}' collection='{CHROMA_COLLECTION_NAME}'")
        _CLIENT = chromadb.CloudClient(
            api_key=CHROMA_API_KEY,
            tenant=CHROMA_TENANT,
            database=CHROMA_DATABASE,
        )
        # If HF API key present, provide embedding function to ensure same transform as ingestion if needed.
        emb_fn = HuggingFaceEmbeddingFunction() if HF_API_KEY else None

        # get_collection will work if the collection exists; if embedding_function is None, Chroma uses stored embeddings/index.
        if emb_fn:
            _COLLECTION = _CLIENT.get_collection(name=CHROMA_COLLECTION_NAME, embedding_function=emb_fn)
        else:
            # If no embedding function, still get the collection (must exist)
            _COLLECTION = _CLIENT.get_collection(name=CHROMA_COLLECTION_NAME)
        print("✅ RAG: Chroma collection connected.")
        return _COLLECTION
    except Exception as e:
        print(f"❌ RAG connection error: {e}")
        _CLIENT = None
        _COLLECTION = None
        return None

def rag_query(user_message: str, n_results: int = 3):
    """
    Query Chroma (pre-chunked, pre-embedded). Returns:
    { "context": str, "chunks": [...], "metadatas": [...] }
    """
    collection = get_collection()
    if not collection:
        return {"context": "", "chunks": [], "metadatas": []}

    try:
        results = collection.query(
            query_texts=[user_message],
            n_results=n_results,
        )
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        context_blocks = []
        for idx, meta in enumerate(metadatas):
            meta = meta or {}
            q = meta.get("question") or meta.get("Q") or "N/A"
            j = meta.get("reponse") or meta.get("J") or meta.get("answer") or "N/A"
            theme = meta.get("theme") or meta.get("topic") or "N/A"
            # Build a compact, human-readable block
            block = (
                f"[THEME: {theme}] Situation: \"{q}\"\n"
                f"Conseil: {j}\n"
            )
            context_blocks.append(block)

        full_context = "\n\n---\n\n".join(context_blocks)
        return {"context": full_context, "chunks": documents, "metadatas": metadatas}
    except Exception as e:
        print(f"⚠️ RAG query error: {e}")
        return {"context": "", "chunks": [], "metadatas": []}

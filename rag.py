# rag.py
import chromadb
import os

# -------------------------
# CHROMA CLOUD CONFIG (depuis .env)
# -------------------------
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY")
CHROMA_TENANT = os.getenv("CHROMA_TENANT")
CHROMA_DATABASE = os.getenv("CHROMA_DATABASE")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "sophia")
# -------------------------
# CONNECT TO CHROMA
# -------------------------
def get_chroma_collection():
    client = chromadb.CloudClient(
        api_key=CHROMA_API_KEY,
        tenant=CHROMA_TENANT,
        database=CHROMA_DATABASE,
    )
    return client.get_collection(CHROMA_COLLECTION)


# -------------------------
# RAG QUERY (no re-embedding)
# -------------------------
def rag_query(user_message: str, n_results: int = 5, theme_filter: str = None):
    """
    Interroge Chroma Cloud (déjà chunkée / déjà encodée).
    Retourne dict: {'context': str, 'chunks': [...], 'metadata': [...]}
    Si theme_filter fourni, on essaye de retourner en priorité des chunks avec ce theme.
    """
    collection = get_chroma_collection()

    # query_texts usage (Chroma Cloud will embed internally or use stored index)
    results = collection.query(
        query_texts=[user_message],
        n_results=n_results,
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    # If theme_filter requested, re-order to prioritize matching theme
    if theme_filter:
        prioritized = []
        others = []
        for doc, meta in zip(documents, metadatas):
            if meta and str(meta.get("theme", "")).lower() == str(theme_filter).lower():
                prioritized.append((doc, meta))
            else:
                others.append((doc, meta))
        ordered = prioritized + others
    else:
        ordered = list(zip(documents, metadatas))

    # Build readable context
    context_blocks = []
    for doc, meta in ordered:
        meta = meta or {}
        block = (
            f"[THEME: {meta.get('theme')} | TYPE: {meta.get('type')} | NIVEAU: {meta.get('niveau_souffrance')} | REDFLAG: {meta.get('redflag')}]\n\n"
            f"QUESTION: {meta.get('question')}\n\n"
            f"RÉPONSE: {meta.get('reponse')}\n\n"
            f"SOURCE:\n{doc}"
        )
        context_blocks.append(block)

    context = "\n\n---\n\n".join(context_blocks)

    return {
        "context": context,
        "chunks": [d for d, m in ordered],
        "metadata": [m for d, m in ordered]
    }

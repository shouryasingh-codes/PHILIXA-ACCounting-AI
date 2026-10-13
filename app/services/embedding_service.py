import logging
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Singleton model instance to prevent multiple heavy loads in memory
_model = None

def get_embedding_model():
    global _model
    if _model is None:
        # Accounting graph imports must not require/load the meeting embedding runtime.
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading embedding model: {settings.embedding_model}")
        _model = SentenceTransformer(settings.embedding_model)
    return _model

def chunk_text(text: str, chunk_size: int = 300, overlap: int = 50) -> list[str]:
    """Basic word-based chunker for meeting notes."""
    words = text.split()
    chunks = []
    i = 0
    if not words:
        return []
    
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return chunks

def generate_embeddings_for_text(text: str) -> list[dict]:
    """Chunks text and returns list of dicts with chunk_text and embedding."""
    model = get_embedding_model()
    chunks = chunk_text(text)
    results = []
    
    for idx, chunk in enumerate(chunks):
        # encode returns a numpy array, convert to list for pgvector
        embedding = model.encode(chunk).tolist()
        results.append({
            "chunk_index": idx,
            "chunk_text": chunk,
            "embedding": embedding
        })
    return results

def generate_query_embedding(query: str) -> list[float]:
    """Generates embedding for a search query."""
    model = get_embedding_model()
    return model.encode(query).tolist()

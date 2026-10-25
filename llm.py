import os
import requests

OLLAMA = os.getenv("OLLAMA_URL", "http://localhost:11434")
CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen2.5:7b-instruct")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")


def embed(texts, kind="document"):
    # nomic-embed-text expects task prefixes
    prefix = "search_query: " if kind == "query" else "search_document: "
    r = requests.post(f"{OLLAMA}/api/embed",
                      json={"model": EMBED_MODEL, "input": [prefix + t for t in texts]}, timeout=300)
    r.raise_for_status()
    return r.json()["embeddings"]


def chat(system, user, temperature=0.1):
    r = requests.post(f"{OLLAMA}/api/chat", json={
        "model": CHAT_MODEL, "stream": False,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": temperature, "num_ctx": 8192},
    }, timeout=600)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()

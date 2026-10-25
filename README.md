# ContextBridge (local, Postgres + pgvector + Ollama)

## Run
    ollama pull qwen2.5:7b-instruct && ollama pull nomic-embed-text
    docker compose up -d
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python seed.py            # resets DB, loads users + synthetic docs
    streamlit run app.py

Env overrides: DATABASE_URL, OLLAMA_URL, CHAT_MODEL, EMBED_MODEL, MAX_DIST (default 0.55).

## Roles
- Employee: own knowledge (+ anything transferred to them)
- Manager: self + direct reports (+ transferred)
- HR: everything, uploads docs, manages users

## Demo script
1. Log in as Riya -> ask "Why Postgres over MongoDB?" -> "I don't know" (not her data).
2. Log in as Manish -> same question -> cited answer with the MongoDB prototype history.
3. Manish -> Team & transfers -> transfer Arjun -> Riya.
4. Log in as Riya -> same question now works; Handover brief tab -> Arjun.
5. Ask something unrelated ("What is our vacation policy?") -> "I don't know".

## v2 additions
- Upload document: title, description, date, file or pasted text (any role; HR/managers can pick the owner).
- Add MOM: meeting date, attendees, minutes + action-item table. Tagged people get it in "My to-do".
- To-do: mark completed with a typed comment and/or uploaded file; assigners see status.
- After updating files, re-run `python seed.py` (schema changed; it resets the DB).

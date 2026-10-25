import os
import re
import numpy as np
from db import query
from llm import embed, chat

# cosine distance cutoff; tune using the distance shown in the UI
MAX_DIST = float(os.getenv("MAX_DIST", "0.55"))
IDK = "I don't know. I couldn't find enough evidence in the knowledge you have access to."

SYSTEM = """You are ContextBridge, an assistant that explains organizational decisions and their history.
Answer using ONLY the numbered snippets provided.
Rules:
1. Cite every factual statement with its snippet number like [1] or [2][3].
2. Explain the reasoning, alternatives considered and the outcome when the snippets contain them.
3. Never use outside knowledge. If the snippets do not contain the answer, reply exactly: I don't know.
4. Be concise."""


def visible_owner_ids(user):
    if user["role"] == "hr":
        rows = query("SELECT id FROM users")
    elif user["role"] == "manager":
        rows = query("SELECT id FROM users WHERE id=%s OR manager_id=%s", (user["id"], user["id"]))
    else:
        rows = query("SELECT id FROM users WHERE id=%s", (user["id"],))
    ids = {r["id"] for r in rows}
    ids |= {r["from_id"] for r in query("SELECT from_id FROM transfers WHERE to_id=%s AND active", (user["id"],))}
    return sorted(ids)


def retrieve(user, question, scope_owner=None, k=6):
    ids = visible_owner_ids(user)
    if scope_owner is not None:
        ids = [i for i in ids if i == scope_owner]
    if not ids:
        return []
    qv = np.array(embed([question], "query")[0], dtype=np.float32)
    # ACL is enforced inside the SQL query, before the LLM ever sees text
    return query("""SELECT c.id, c.text, d.title, d.description, d.source_type, d.created_at, u.name AS owner,
                           (c.embedding <=> %s) AS dist
                    FROM chunks c JOIN documents d ON d.id=c.doc_id JOIN users u ON u.id=c.owner_id
                    WHERE c.owner_id = ANY(%s) ORDER BY dist LIMIT %s""", (qv, ids, k))


def _context(rows):
    return "\n\n".join(f"[{i}] (source: {r['title']} | {r['source_type']} | {r['owner']} | {r['created_at']}"
                       f"{' | ' + r['description'] if r.get('description') else ''})\n{r['text']}"
                       for i, r in enumerate(rows, 1))


def _finalize(answer, rows):
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer) if 0 < int(n) <= len(rows)})
    if answer.lower().startswith("i don't know") or not cited:  # guard: no evidence -> abstain
        return {"answer": IDK, "sources": [], "abstained": True}
    return {"answer": answer, "abstained": False,
            "sources": [{"n": n, **rows[n - 1]} for n in cited]}


def ask(user, question, scope_owner=None):
    rows = [r for r in retrieve(user, question, scope_owner) if r["dist"] <= MAX_DIST]
    if not rows:  # retrieval gate: don't even call the LLM
        return {"answer": IDK, "sources": [], "abstained": True}
    answer = chat(SYSTEM, f"Snippets:\n{_context(rows)}\n\nQuestion: {question}")
    return _finalize(answer, rows)


def handover_brief(user, from_id):
    if from_id not in visible_owner_ids(user):
        return {"answer": "You are not authorised to view this person's knowledge.", "sources": [], "abstained": True}
    rows = query("""SELECT c.text, d.title, d.source_type, d.created_at, u.name AS owner, 0.0 AS dist
                    FROM chunks c JOIN documents d ON d.id=c.doc_id JOIN users u ON u.id=c.owner_id
                    WHERE c.owner_id=%s ORDER BY d.created_at, c.doc_id, c.idx LIMIT 30""", (from_id,))
    if not rows:
        return {"answer": "No knowledge on file for this person.", "sources": [], "abstained": True}
    prompt = (f"Snippets:\n{_context(rows)}\n\nWrite a handover brief for the person taking over from {rows[0]['owner']}. "
              "Use these sections: Role & responsibilities; Key decisions and why they were made (include alternatives rejected); "
              "Workarounds / gotchas; Open items & risks. Cite every point with [n]. Only use the snippets.")
    return _finalize(chat(SYSTEM, prompt, temperature=0.2), rows)

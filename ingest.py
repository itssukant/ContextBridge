import io
import json
import re
import numpy as np
from db import query
from llm import embed


def extract_text(filename, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        return "\n\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    text = data.decode("utf-8", errors="ignore")
    if name.endswith(".json"):  # chat export: [{"user","ts","text"}, ...]
        try:
            msgs = json.loads(text)
            return "\n".join(f"[{m.get('ts','')}] {m.get('user','?')}: {m.get('text','')}" for m in msgs)
        except Exception:
            return text
    return text


def chunk_text(text, size=900, overlap=150):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 <= size:
            cur = (cur + "\n\n" + p).strip()
        else:
            if cur:
                chunks.append(cur)
            while len(p) > size:
                chunks.append(p[:size])
                p = p[size - overlap:]
            cur = p
    if cur:
        chunks.append(cur)
    return chunks


def ingest_document(owner_id, title, source_type, text, created_at=None, description=""):
    doc = query("INSERT INTO documents(owner_id,title,description,source_type,content,created_at) "
                "VALUES (%s,%s,%s,%s,%s,COALESCE(%s::date, CURRENT_DATE)) RETURNING id",
                (owner_id, title, description, source_type, text, created_at))[0]
    chunks = chunk_text(text)
    vecs = embed([f"{title}\n{description}\n{c}" for c in chunks])
    for i, (c, v) in enumerate(zip(chunks, vecs)):
        query("INSERT INTO chunks(doc_id,owner_id,idx,text,embedding) VALUES (%s,%s,%s,%s,%s)",
              (doc["id"], owner_id, i, c, np.array(v, dtype=np.float32)))
    return doc["id"], len(chunks)


def index_task_completion(task_id):
    """Index a completed task's note (and readable attachment) so the model can use it."""
    rows = query("""SELECT t.*, d.title AS mom_title, d.created_at AS mom_date,
                           cu.name AS by_name, au.name AS assignee_name
                    FROM tasks t JOIN documents d ON d.id=t.mom_doc_id
                    JOIN users cu ON cu.id=t.created_by JOIN users au ON au.id=t.assignee_id
                    WHERE t.id=%s AND t.status='done'""", (task_id,))
    if not rows or rows[0]["completion_doc_id"]:
        return None
    t = rows[0]
    parts = [f"Task completed: {t['title']}",
             f"Meeting: {t['mom_title']} ({t['mom_date']})",
             f"Assigned by: {t['by_name']}",
             f"Completed by: {t['assignee_name']} on {t['completed_at']:%Y-%m-%d}"]
    if t["completion_comment"]:
        parts += ["", "Completion note:", t["completion_comment"]]
    fname = (t["completion_file_name"] or "").lower()
    if t["completion_file"] is not None and fname.endswith((".txt", ".md", ".json", ".csv", ".pdf")):
        try:
            extra = extract_text(fname, bytes(t["completion_file"])).strip()
            if extra:
                parts += ["", f"Attached file ({t['completion_file_name']}):", extra[:6000]]
        except Exception:
            pass
    doc_id, _ = ingest_document(t["assignee_id"], f"Task completed: {t['title']}", "task", "\n".join(parts),
                                t["completed_at"].date(),
                                f"Completion update for a task from meeting '{t['mom_title']}'")
    query("UPDATE tasks SET completion_doc_id=%s WHERE id=%s", (doc_id, task_id))
    return doc_id

from db import query
from ingest import index_task_completion
for r in query("SELECT id FROM tasks WHERE status='done' AND completion_doc_id IS NULL"):
    print("indexed task", r["id"], "->", index_task_completion(r["id"]))

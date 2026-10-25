import datetime as dt
import pandas as pd
import psycopg2
import streamlit as st
from db import query
import rag
from ingest import extract_text, ingest_document, index_task_completion

st.set_page_config(page_title="ContextBridge", page_icon="🌉", layout="wide")

# ---------- demo login ----------
all_users = query("SELECT * FROM users ORDER BY role DESC, name")
by_id = {u["id"]: u for u in all_users}
st.sidebar.title("🌉 ContextBridge")
me_id = st.sidebar.selectbox("Log in as", [u["id"] for u in all_users],
                             format_func=lambda i: f"{by_id[i]['name']} · {by_id[i]['role']}")
me = by_id[me_id]
st.sidebar.caption(f"Role: **{me['role']}**" + (" · on notice" if me["on_notice"] else ""))

visible = rag.visible_owner_ids(me)
transferred_in = {r["from_id"] for r in query("SELECT from_id FROM transfers WHERE to_id=%s AND active", (me_id,))}
open_count = query("SELECT COUNT(*) AS n FROM tasks WHERE assignee_id=%s AND status='open'", (me_id,))[0]["n"]


def label(i):
    return by_id[i]["name"] + (" (transferred to you)" if i in transferred_in else "")


def show_sources(res):
    for s in res["sources"]:
        with st.expander(f"[{s['n']}] {s['title']} · {s['owner']} · {s['created_at']}"):
            if s.get("description"):
                st.caption(s["description"])
            st.write(s["text"])
            if s.get("dist"):
                st.caption(f"distance {s['dist']:.3f}")


def managed_users():
    if me["role"] == "hr":
        return [u for u in all_users if u["role"] != "hr"]
    return [u for u in all_users if u["manager_id"] == me_id]


T_ASK, T_DOCS, T_UP, T_MOM = "💬 Ask", "📄 Documents", "⬆️ Upload document", "📝 Add MOM"
T_TODO = f"✅ My to-do ({open_count})"
T_BRIEF, T_TEAM, T_ADMIN = "📋 Handover brief", "👥 Team & transfers", "🛠 Admin"
tab_names = [T_ASK, T_TODO, T_UP, T_MOM, T_DOCS, T_BRIEF]
if me["role"] in ("manager", "hr"):
    tab_names.append(T_TEAM)
if me["role"] == "hr":
    tab_names.append(T_ADMIN)
tabs = dict(zip(tab_names, st.tabs(tab_names)))

# ---------- chat ----------
with tabs[T_ASK]:
    scope = st.selectbox("Search in", [None] + visible,
                         format_func=lambda i: "Everything I can access" if i is None else label(i))
    key = f"hist_{me_id}"
    st.session_state.setdefault(key, [])
    for m in st.session_state[key]:
        with st.chat_message(m["role"]):
            st.write(m["content"])
            if m.get("sources"):
                show_sources(m)
    if q := st.chat_input("e.g. Why did we choose Postgres over MongoDB for billing?"):
        st.session_state[key].append({"role": "user", "content": q})
        with st.chat_message("user"):
            st.write(q)
        with st.chat_message("assistant"):
            with st.spinner("Searching and thinking locally..."):
                res = rag.ask(me, q, scope)
            st.write(res["answer"])
            show_sources(res)
        st.session_state[key].append({"role": "assistant", "content": res["answer"], "sources": res["sources"]})

# ---------- upload document ----------
with tabs[T_UP]:
    st.subheader("Upload a document")
    if me["role"] == "hr":
        owner_opts = [u["id"] for u in all_users if u["role"] != "hr"]
    elif me["role"] == "manager":
        owner_opts = [me_id] + [u["id"] for u in managed_users()]
    else:
        owner_opts = [me_id]
    with st.form("upload_form", clear_on_submit=True):
        owner = st.selectbox("Knowledge belongs to", owner_opts, format_func=lambda i: by_id[i]["name"])
        title = st.text_input("Title *")
        description = st.text_area("Description *", help="What is this document and why does it matter?", height=90)
        doc_date = st.date_input("Document date *", value=dt.date.today())
        stype = st.selectbox("Type", ["doc", "chat", "transcript"])
        f = st.file_uploader("File (txt, md, json chat export, pdf)", type=["txt", "md", "json", "pdf"])
        pasted = st.text_area("...or paste the text here", height=120)
        go = st.form_submit_button("Upload & index")
    if go:
        text = extract_text(f.name, f.read()) if f else pasted
        if not (title.strip() and description.strip() and text.strip()):
            st.error("Title, description and a file or pasted text are required.")
        else:
            with st.spinner("Chunking and embedding locally..."):
                _, n = ingest_document(owner, title.strip(), stype, text.strip(), doc_date, description.strip())
            st.success(f"Indexed '{title}' ({n} chunks) under {by_id[owner]['name']}.")

# ---------- add MOM ----------
with tabs[T_MOM]:
    st.subheader("Add Minutes of Meeting")
    names = [u["name"] for u in all_users]
    with st.form("mom_form"):
        mt = st.text_input("Meeting title *")
        md = st.date_input("Meeting date *", value=dt.date.today())
        attendees = st.multiselect("Attendees", names)
        notes = st.text_area("Minutes / meeting context *", height=220,
                             help="Discussion, decisions and the reasoning behind them.")
        st.markdown("**Action items** - tag the person responsible; it lands in their to-do.")
        items = st.data_editor(
            pd.DataFrame({"Task": pd.Series([""], dtype="object"),
                          "Assigned to": pd.Series([None], dtype="object"),
                          "Due date": pd.to_datetime(pd.Series([None]))}),
            num_rows="dynamic", use_container_width=True, key="mom_items",
            column_config={"Task": st.column_config.TextColumn("Task", width="large"),
                           "Assigned to": st.column_config.SelectboxColumn("Assigned to", options=names),
                           "Due date": st.column_config.DateColumn("Due date")})
        save = st.form_submit_button("Save MOM")
    if save:
        if not (mt.strip() and notes.strip()):
            st.error("Meeting title and minutes are required.")
        else:
            tasks = [r for _, r in items.iterrows() if str(r["Task"]).strip() and r["Assigned to"] in names]
            lines = [f"Meeting: {mt}", f"Date: {md}", f"Attendees: {', '.join(attendees) or 'n/a'}", "",
                     "Minutes:", notes.strip(), "", "Action items:"]
            lines += [f"- {r['Task']} (assigned to {r['Assigned to']}"
                      + (f", due {r['Due date'].date()}" if pd.notna(r["Due date"]) else "") + ")" for r in tasks]
            with st.spinner("Indexing MOM locally..."):
                doc_id, n = ingest_document(me_id, mt.strip(), "mom", "\n".join(lines), md,
                                            f"Minutes of meeting held on {md}")
            name_to_id = {u["name"]: u["id"] for u in all_users}
            for r in tasks:
                due = r["Due date"].date() if pd.notna(r["Due date"]) else None
                query("INSERT INTO tasks(mom_doc_id,title,assignee_id,created_by,due_date) VALUES (%s,%s,%s,%s,%s)",
                      (doc_id, str(r["Task"]).strip(), name_to_id[r["Assigned to"]], me_id, due))
            st.success(f"MOM saved and indexed ({n} chunks). {len(tasks)} action item(s) sent to to-do lists.")

# ---------- to-do ----------
with tabs[T_TODO]:
    st.subheader("Assigned to me")
    mine = query("""SELECT t.*, d.title AS mom_title, d.created_at AS mom_date, cu.name AS by_name
                    FROM tasks t JOIN documents d ON d.id=t.mom_doc_id JOIN users cu ON cu.id=t.created_by
                    WHERE t.assignee_id=%s AND t.status='open' ORDER BY t.due_date NULLS LAST, t.id""", (me_id,))
    if not mine:
        st.success("Nothing pending. 🎉")
    for t in mine:
        due = f" · due {t['due_date']}" if t["due_date"] else ""
        with st.container(border=True):
            st.markdown(f"**{t['title']}**")
            st.caption(f"From MOM '{t['mom_title']}' ({t['mom_date']}) · assigned by {t['by_name']}{due}")
            with st.form(f"done_{t['id']}", clear_on_submit=True):
                comment = st.text_area("Completion comment", key=f"c{t['id']}", height=80)
                proof = st.file_uploader("...or upload a file", key=f"f{t['id']}")
                if st.form_submit_button("Mark completed"):
                    if not comment.strip() and not proof:
                        st.error("Add a comment or upload a file.")
                    else:
                        query("""UPDATE tasks SET status='done', completed_at=NOW(), completion_comment=%s,
                                 completion_file_name=%s, completion_file=%s WHERE id=%s""",
                              (comment.strip() or None, proof.name if proof else None,
                               psycopg2.Binary(proof.read()) if proof else None, t["id"]))
                        with st.spinner("Adding your update to the knowledge base..."):
                            index_task_completion(t["id"])
                        st.rerun()

    done = query("SELECT * FROM tasks WHERE assignee_id=%s AND status='done' ORDER BY completed_at DESC", (me_id,))
    if done:
        st.subheader("Completed")
        for t in done:
            with st.expander(f"✔ {t['title']} · {t['completed_at']:%Y-%m-%d %H:%M}"):
                st.write(t["completion_comment"] or "_No comment_")
                if t["completion_file"] is not None:
                    st.download_button(f"Download {t['completion_file_name']}", bytes(t["completion_file"]),
                                       file_name=t["completion_file_name"], key=f"dl{t['id']}")

    st.subheader("Assigned by me to others")
    given = query("""SELECT t.id, t.title, u.name AS assignee, t.due_date, t.status, t.completed_at,
                            t.completion_comment, t.completion_file_name, t.completion_file
                     FROM tasks t JOIN users u ON u.id=t.assignee_id
                     WHERE t.created_by=%s AND t.assignee_id<>%s ORDER BY t.status DESC, t.due_date""", (me_id, me_id))
    if not given:
        st.caption("None yet.")
    for t in given:
        icon = "✔" if t["status"] == "done" else "⏳"
        due = f" · due {t['due_date']}" if t["due_date"] else ""
        with st.expander(f"{icon} {t['title']} → {t['assignee']}{due}"):
            if t["status"] == "done":
                st.caption(f"Completed {t['completed_at']:%Y-%m-%d %H:%M}")
                st.write(t["completion_comment"] or "_No comment_")
                if t["completion_file"] is not None:
                    st.download_button(f"Download {t['completion_file_name']}", bytes(t["completion_file"]),
                                       file_name=t["completion_file_name"], key=f"gdl{t['id']}")
            else:
                st.caption("Still open")

# ---------- documents ----------
with tabs[T_DOCS]:
    docs = query("""SELECT d.title, d.description, d.source_type AS type, d.created_at AS date, u.name AS owner
                    FROM documents d JOIN users u ON u.id=d.owner_id
                    WHERE d.owner_id = ANY(%s) ORDER BY d.created_at DESC""", (visible,))
    st.dataframe(docs, use_container_width=True)

# ---------- handover brief ----------
with tabs[T_BRIEF]:
    cands = [i for i in visible if i != me_id]
    if not cands:
        st.info("No one else's knowledge is available to you.")
    else:
        who = st.selectbox("Generate brief for", cands, format_func=label)
        if st.button("Generate brief"):
            with st.spinner("Writing brief..."):
                res = rag.handover_brief(me, who)
            st.markdown(res["answer"])
            show_sources(res)

# ---------- team & transfers ----------
if T_TEAM in tabs:
    with tabs[T_TEAM]:
        team = managed_users()
        st.subheader("Notice status")
        for u in team:
            on = st.checkbox(f"{u['name']} is on notice period", value=u["on_notice"], key=f"n{u['id']}")
            if on != u["on_notice"]:
                query("UPDATE users SET on_notice=%s WHERE id=%s", (on, u["id"]))
                st.rerun()
        st.subheader("Transfer knowledge")
        leaving = [u for u in team if u["on_notice"]]
        if not leaving:
            st.info("No one in your team is on notice.")
        else:
            c1, c2 = st.columns(2)
            frm = c1.selectbox("From (on notice)", [u["id"] for u in leaving], format_func=lambda i: by_id[i]["name"])
            to_opts = [u["id"] for u in all_users if u["id"] != frm and u["role"] != "hr" and not u["on_notice"]]
            to = c2.selectbox("To", to_opts, format_func=lambda i: by_id[i]["name"])
            if st.button("Transfer knowledge"):
                if query("SELECT 1 FROM transfers WHERE from_id=%s AND to_id=%s AND active", (frm, to)):
                    st.warning("This transfer already exists.")
                else:
                    query("INSERT INTO transfers(from_id,to_id,created_by) VALUES (%s,%s,%s)", (frm, to, me_id))
                    st.success(f"{by_id[to]['name']} can now access {by_id[frm]['name']}'s knowledge.")
        st.subheader("Active transfers")
        for t in query("SELECT * FROM transfers WHERE active ORDER BY created_at DESC"):
            if me["role"] == "hr" or by_id[t["from_id"]]["manager_id"] == me_id:
                a, b = st.columns([4, 1])
                a.write(f"{by_id[t['from_id']]['name']} → {by_id[t['to_id']]['name']} (by {by_id[t['created_by']]['name']})")
                if b.button("Revoke", key=f"r{t['id']}"):
                    query("UPDATE transfers SET active=FALSE WHERE id=%s", (t["id"],))
                    st.rerun()

# ---------- admin ----------
if T_ADMIN in tabs:
    with tabs[T_ADMIN]:
        st.subheader("Add user")
        nm = st.text_input("Name")
        role = st.selectbox("Role", ["employee", "manager"])
        mgr = st.selectbox("Reports to", [None] + [u["id"] for u in all_users if u["role"] == "manager"],
                           format_func=lambda i: "—" if i is None else by_id[i]["name"])
        if st.button("Create user") and nm:
            query("INSERT INTO users(name,role,manager_id) VALUES (%s,%s,%s)", (nm, role, mgr))
            st.rerun()

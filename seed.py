"""Resets the DB and loads users + synthetic documents. Run: python seed.py"""
from db import init_schema, query
from ingest import ingest_document

init_schema()


def add_user(name, role, manager=None, on_notice=False):
    return query("INSERT INTO users(name,role,manager_id,on_notice) VALUES (%s,%s,%s,%s) RETURNING id",
                 (name, role, manager, on_notice))[0]["id"]


hr = add_user("Hina (HR)", "hr")
manish = add_user("Manish (Manager)", "manager")
meera = add_user("Meera (Manager)", "manager")
arjun = add_user("Arjun", "employee", manish, on_notice=True)
riya = add_user("Riya", "employee", manish)
karan = add_user("Karan", "employee", meera)
sneha = add_user("Sneha", "employee", meera)

DOCS = [
 (arjun, "ADR-007: Billing datastore - PostgreSQL over MongoDB", "doc", "2025-03-12", """
# ADR-007: Billing service datastore
Status: Accepted. Author: Arjun. Date: 2025-03-12.

## Context
The billing service stores invoices, ledger entries and payment attempts. We needed a primary datastore before the Q2 launch.

## Options considered
1. MongoDB - attractive for flexible invoice schemas. We ran a two-week prototype in February.
2. PostgreSQL 15 - relational integrity, JSONB for variable invoice metadata.
3. DynamoDB - rejected early because of vendor lock-in and expensive scans for finance reporting.

## What we tried first
The MongoDB prototype failed on two points: multi-document transactions for double-entry ledger writes were slow and awkward, and the finance team's reconciliation queries (joins across invoices, payments and refunds) needed painful aggregation pipelines.

## Decision
Use PostgreSQL 15. Store variable invoice attributes in a JSONB column. Partition the invoices table by month.

## Consequences
Strong consistency for the ledger. Finance can use plain SQL. We accepted that schema migrations need more care than with MongoDB.
"""),
 (arjun, "#billing-eng Slack thread - duplicate webhooks", "chat", "2025-05-08", """
[2025-05-08 10:02] Arjun: Payments gateway is sending duplicate webhooks again, we double-credited 14 invoices last night.
[2025-05-08 10:05] Priya: Can we just drop the dedupe table now that we added retries?
[2025-05-08 10:07] Arjun: Please do NOT remove the webhook_dedupe table. The gateway retries up to 5 times with the same event id, and the dedupe table is the only thing that makes handlers idempotent.
[2025-05-08 10:15] Arjun: Workaround in place: a nightly reconciliation job runs at 02:00 IST and compares gateway settlements against our ledger. Mismatches go to #billing-alerts.
[2025-05-08 10:20] Priya: Got it. Should we move the job to Airflow?
[2025-05-08 10:22] Arjun: Later. For now it is a cron on the billing-worker host, documented in the runbook. Airflow migration is parked until Q4.
"""),
 (arjun, "Billing retro meeting transcript", "transcript", "2025-06-20", """
Manish: Let's start with what went wrong in the June release.
Arjun: The gateway had a 40 minute outage and our retry storm made it worse. We were retrying every second with no backoff.
Manish: What did we decide?
Arjun: Exponential backoff with jitter, capped at 5 minutes, and a circuit breaker per gateway. I'll write that into the runbook.
Manish: And the idempotency keys?
Arjun: We agreed every write endpoint takes an Idempotency-Key header. Finance asked for refunds to be included, so that is in scope too.
Manish: Okay. Action items: Arjun documents backoff settings, Riya updates the checkout client to send idempotency keys.
"""),
 (riya, "Frontend decision: Vite over Next.js", "doc", "2025-04-02", """
# Decision: Checkout frontend build tool
We chose React with Vite instead of Next.js for the checkout app. The app is a single-page widget embedded in partner sites, so server-side rendering gave no benefit and increased deployment complexity. Vite gave sub-second hot reload and a 40 percent smaller bundle in our test. We revisit if SEO pages are needed.
"""),
 (karan, "Kubernetes upgrade runbook", "doc", "2025-07-15", """
# Runbook: cluster upgrade 1.28 to 1.30
Upgrade one minor version at a time. Cordon and drain nodes in batches of two. Take an etcd snapshot before starting. The ingress controller must be upgraded before the control plane, otherwise the admission webhook fails and deployments hang. Rollback: restore the etcd snapshot and recreate the node pool.
"""),
 (sneha, "Test strategy for payments", "doc", "2025-05-30", """
# Test strategy
Contract tests against the gateway sandbox run on every merge. End-to-end checkout tests run nightly. We replay recorded duplicate webhooks to verify idempotency. Flaky tests are quarantined within 24 hours and tracked in the QA board.
"""),
]
ids = {}
for owner, title, stype, date, text in DOCS:
    ids[title], n = ingest_document(owner, title, stype, text.strip(), date)
    print("ingested", title, n, "chunks")

retro = ids["Billing retro meeting transcript"]
for title, assignee, due in [("Document backoff and circuit-breaker settings in the runbook", arjun, "2025-07-01"),
                             ("Update checkout client to send Idempotency-Key header", riya, "2025-07-05")]:
    query("INSERT INTO tasks(mom_doc_id,title,assignee_id,created_by,due_date) VALUES (%s,%s,%s,%s,%s)",
          (retro, title, assignee, manish, due))
print("Seed complete. Arjun is on notice; Manish can transfer his knowledge.")

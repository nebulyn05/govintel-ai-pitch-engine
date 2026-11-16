"""Local-only human review dashboard for research and pitch drafts.

Run with: python -m scripts.review_dashboard
Binds to 127.0.0.1 only. It never sends outreach.
"""
from __future__ import annotations

import argparse
import html
import os
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from scripts.db import connect, init_db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = secrets.token_urlsafe(32)


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def page(title: str, body: str) -> bytes:
    return ("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GovIntel Review — """ + esc(title) + """</title>
<style>
:root{color-scheme:light dark;font:16px system-ui,sans-serif}
body{max-width:1100px;margin:2rem auto;padding:0 1rem;line-height:1.5}
a{color:#68a9ff}header,section,article{border:1px solid #8886;border-radius:10px;padding:1rem;margin:1rem 0}
small,.muted{opacity:.75}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#8881;padding:.8rem;border-radius:6px}
input,textarea,button{font:inherit;padding:.65rem;max-width:100%}
textarea{width:100%;min-height:150px}label{display:block;margin:.6rem 0}
button{cursor:pointer;margin:.25rem}.danger{border:1px solid #c66}
</style></head><body><header><a href="/">GovIntel AI Pitch Engine</a> / Human review
<p class="muted">Local review only. No email, CRM delivery, or outreach sending.</p></header>""" + body + "</body></html>").encode()


def load_queue():
    with connect() as conn:
        return conn.execute("""SELECT p.id,p.lead_id,p.version,p.outcome,p.opportunity_summary,
            p.proposed_solution,p.created_at,l.company_name,l.website,l.naics_code,l.city,l.state,
            COALESCE(best.priority_score,0) AS priority_score,
            COALESCE(best.evidence_score,0) AS evidence_score,
            COALESCE(best.title,'No scored opportunity') AS top_opportunity
            FROM pitch_drafts p JOIN leads l ON l.id=p.lead_id
            LEFT JOIN LATERAL (SELECT o.priority_score,o.evidence_score,o.title
                FROM opportunities o WHERE o.lead_id=p.lead_id
                ORDER BY o.priority_score DESC,o.id DESC LIMIT 1) best ON TRUE
            WHERE COALESCE(p.review_status,'pending')='pending'
            ORDER BY priority_score DESC,evidence_score DESC,p.created_at DESC,p.id DESC LIMIT 200""").fetchall()


def load_detail(draft_id: int):
    with connect() as conn:
        draft = conn.execute("""SELECT p.*,l.company_name,l.website,l.naics_code,l.city,l.state,
            l.contact_name,l.contact_title,l.campaign_id
            FROM pitch_drafts p JOIN leads l ON l.id=p.lead_id WHERE p.id=%s""",
            (draft_id,)).fetchone()
        if not draft:
            return None, [], []
        evidence = conn.execute("""SELECT id,source_url,source_title,excerpt,evidence_type,
            confidence,retrieved_at FROM evidence_items WHERE lead_id=%s
            ORDER BY retrieved_at DESC,id DESC LIMIT 100""", (draft["lead_id"],)).fetchall()
        opportunities = conn.execute("""SELECT o.*,COALESCE(jsonb_agg(
            jsonb_build_object('title',sc.title,'delivery_status',sc.delivery_status,
            'match_score',sc.match_score,'registry_status',sr.status,'prerequisites',
            sc.match_metadata->'prerequisites') ORDER BY sc.match_score DESC)
            FILTER (WHERE sc.id IS NOT NULL),'[]'::jsonb) AS matches
            FROM opportunities o LEFT JOIN solution_candidates sc ON sc.opportunity_id=o.id
            LEFT JOIN solution_registry sr ON sr.id=sc.solution_registry_id
            WHERE o.lead_id=%s GROUP BY o.id ORDER BY o.priority_score DESC,o.id DESC LIMIT 20""",
            (draft["lead_id"],)).fetchall()
    return draft, evidence, opportunities


def record_review(draft_id: int, action: str, reviewer: str, reason: str, edited_pitch: str):
    if action not in {"approve", "edit", "reject", "research"}:
        raise ValueError("Unsupported review action.")
    if not reviewer.strip():
        raise ValueError("Reviewer identity is required.")
    if action in {"reject", "research"} and not reason.strip():
        raise ValueError("Add a reason for rejection or further research.")
    with connect() as conn:
        draft = conn.execute("""SELECT p.*,l.id AS scoped_lead_id FROM pitch_drafts p
            JOIN leads l ON l.id=p.lead_id WHERE p.id=%s FOR UPDATE OF p""",
            (draft_id,)).fetchone()
        if not draft:
            raise ValueError("Draft not found.")
        if draft.get("review_status", "pending") != "pending":
            raise ValueError("This draft has already been reviewed.")
        new_pitch = draft["pitch_text"]
        new_status = "pending"
        approved_at = None
        if action == "edit":
            if not edited_pitch.strip():
                raise ValueError("Edited pitch cannot be empty.")
            new_pitch = edited_pitch.strip()
        elif action == "approve":
            checks = draft["quality_checks"] or {}
            claims = draft["claims"] or []
            source_backed = any(
                isinstance(c, dict) and c.get("evidence_type") in
                {"verified_fact", "evidence_supported_inference"} and
                isinstance(c.get("source_urls"), list) and len(c["source_urls"]) > 0
                for c in claims
            )
            if draft["outcome"] != "pitch_ready" or not checks.get("source_backed_claims") or not source_backed:
                raise ValueError("Approval blocked: draft must be pitch_ready and contain source-backed claims.")
            if not draft["proposed_solution"].strip():
                raise ValueError("Approval blocked: no approved solution is attached.")
            matched = conn.execute("""SELECT 1 FROM solution_candidates sc
                JOIN solution_registry sr ON sr.id=sc.solution_registry_id
                JOIN opportunities o ON o.id=sc.opportunity_id
                WHERE o.lead_id=%s AND sr.status='approved'
                AND sr.delivery_status IN ('available','buildable','partner_required')
                AND sr.description=%s
                AND sr.id=(SELECT latest.id FROM solution_registry latest
                    WHERE latest.solution_key=sr.solution_key AND latest.status='approved'
                    AND latest.delivery_status IN ('available','buildable','partner_required')
                    ORDER BY latest.version DESC,latest.reviewed_at DESC LIMIT 1)
                LIMIT 1""", (draft["lead_id"],draft["proposed_solution"])).fetchone()
            if not matched:
                raise ValueError("Approval blocked: no currently approved solution match is recorded.")
            new_status = "approved"
            approved_at = "NOW()"
        elif action == "reject":
            new_status = "rejected"
        elif action == "research":
            new_status = "needs_further_research"
        if action == "approve":
            conn.execute("""UPDATE pitch_drafts SET pitch_text=%s,review_status=%s,
                approved_by=%s,approved_at=NOW(),reviewed_by=%s,reviewed_at=NOW(),reviewer_notes=%s
                WHERE id=%s""", (new_pitch,new_status,reviewer.strip(),reviewer.strip(),reason.strip(),draft_id))
        else:
            conn.execute("""UPDATE pitch_drafts SET pitch_text=%s,review_status=%s,
                reviewed_by=%s,reviewed_at=NOW(),reviewer_notes=%s WHERE id=%s""",
                (new_pitch,new_status,reviewer.strip(),reason.strip(),draft_id))
        conn.execute("""INSERT INTO outcomes(company_id,lead_id,pitch_draft_id,outcome_type,outcome_value)
            VALUES (%s,%s,%s,%s,%s)""",
            (draft["company_id"],draft["lead_id"],draft_id,
             {"approve":"human_approved","edit":"human_edited","reject":"human_rejected",
              "research":"human_requested_research"}[action],
             {"reviewer":reviewer.strip(),"reason":reason.strip(),"action":action}))


class Handler(BaseHTTPRequestHandler):
    server_version = "GovIntelReview/1.0"

    def send_page(self, title, body, status=200):
        payload = page(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            rows = load_queue()
            items = "".join(
                f'<article><h3><a href="/draft/{r["id"]}">{esc(r["company_name"])}</a></h3>'
                f'<p>{esc(r["website"])} · {esc(r["city"])} {esc(r["state"])} · '
                f'NAICS {esc(r["naics_code"])}</p><p>{esc(r["outcome"])} · '
                f'Version {r["version"]}</p><p><b>Priority:</b> {esc(r["priority_score"])}/100 · '
                f'<b>Evidence:</b> {esc(r["evidence_score"])}/100</p>'
                f'<p><b>Top opportunity:</b> {esc(r["top_opportunity"])}</p>'
                f'<p>{esc(r["opportunity_summary"])}</p></article>'
                for r in rows)
            self.send_page("Review queue", f'<h1>Pending review ({len(rows)})</h1>{items or "<p>No drafts awaiting review.</p>"}')
            return
        if parsed.path.startswith("/draft/"):
            try:
                draft_id = int(parsed.path.rsplit("/",1)[1])
            except ValueError:
                self.send_error(404); return
            draft,evidence,opps = load_detail(draft_id)
            if not draft:
                self.send_error(404); return
            claims = draft["claims"] or []
            claim_html = "".join(f'<article><b>Claim {i+1}</b><p>{esc(c.get("claim",""))}</p>'
                f'<p>{esc(c.get("evidence_type"))} · confidence {esc(c.get("confidence"))}</p>'
                f'<p>Sources: {"; ".join(esc(u) for u in c.get("source_urls",[]))}</p></article>'
                for i,c in enumerate(claims) if isinstance(c,dict))
            ev_html = "".join(f'<article><a href="{esc(e["source_url"])}" rel="noopener noreferrer">{esc(e["source_title"] or e["source_url"])}</a>'
                f'<p>{esc(e["evidence_type"])} · {esc(e["retrieved_at"])}</p><pre>{esc(e["excerpt"])}</pre></article>'
                for e in evidence)
            opp_html = "".join(f'<article><b>{esc(o["title"])}</b> — {esc(o["priority_score"])}/100'
                f'<p>{esc(o["evidence_type"])} · impact {esc(o["impact"])} · urgency {esc(o["urgency"])}</p>'
                f'<p>{esc(o["description"])}</p><p>Evidence claim indices: {esc(o["evidence_claim_indices"])}</p>'
                f'<pre>{esc(o["matches"])}</pre></article>' for o in opps)
            body = f"""<h1>{esc(draft["company_name"])}</h1>
<p>{esc(draft["website"])} · NAICS {esc(draft["naics_code"])} · {esc(draft["city"])} {esc(draft["state"])}</p>
<section><h2>Draft status: {esc(draft["outcome"])} / {esc(draft.get("review_status","pending"))}</h2>
<p><b>Proposed solution:</b> {esc(draft["proposed_solution"])}</p>
<p><b>Opportunity summary:</b> {esc(draft["opportunity_summary"])}</p>
<p><b>Channel:</b> {esc(draft["channel"])}</p><h3>Pitch draft</h3><pre>{esc(draft["pitch_text"])}</pre>
<p><b>Quality checks</b></p><pre>{esc(draft["quality_checks"])}</pre>
<p><b>Assumptions</b></p><pre>{esc(draft["assumptions"])}</pre></section>
<section><h2>Claims and source references</h2>{claim_html or "<p>No claims recorded.</p>"}</section>
<section><h2>Evidence captured</h2>{ev_html or "<p>No evidence captured.</p>"}</section>
<section><h2>Opportunities and solution matches</h2>{opp_html or "<p>No opportunity records.</p>"}</section>
<section><h2>Human decision</h2><form method="post" action="/review">
<input type="hidden" name="token" value="{TOKEN}"><input type="hidden" name="draft_id" value="{draft_id}">
<label>Reviewer identity <input name="reviewer" required maxlength="160"></label>
<label>Reason / review notes <textarea name="reason" maxlength="4000"></textarea></label>
<label>Edited pitch (used only for Edit) <textarea name="edited_pitch" maxlength="12000">{esc(draft["pitch_text"])}</textarea></label>
<button name="action" value="approve">Approve draft</button>
<button name="action" value="edit">Save edit (keep pending)</button>
<button class="danger" name="action" value="reject">Reject</button>
<button name="action" value="research">Request further research</button>
</form></section><p><a href="/">Back to queue</a></p>"""
            self.send_page("Draft review",body)
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/review":
            self.send_error(404); return
        try:
            length = int(self.headers.get("Content-Length","0"))
            if length < 1 or length > 30000:
                raise ValueError("Invalid form size.")
            form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            one = lambda key: form.get(key,[""])[0]
            if not secrets.compare_digest(one("token"),TOKEN):
                raise ValueError("Invalid review token; reload the page.")
            draft_id = int(one("draft_id"))
            record_review(draft_id,one("action"),one("reviewer"),one("reason"),one("edited_pitch"))
            self.send_page("Review saved",'<h1>Review recorded</h1><p>The decision and reviewer metadata were saved to the audit trail.</p><a href="/">Return to queue</a>')
        except Exception as exc:
            self.send_page("Review error",f'<h1>Review not saved</h1><p>{esc(exc)}</p><a href="/">Return to queue</a>',400)


def main():
    load_dotenv(os.path.join(ROOT,".env"))
    parser=argparse.ArgumentParser(description="Run the local-only GovIntel human review dashboard")
    parser.add_argument("--host",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=8765)
    args=parser.parse_args()
    if args.host not in {"127.0.0.1","localhost"}:
        parser.error("Dashboard must bind to loopback only.")
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535.")
    init_db()
    server=HTTPServer((args.host,args.port),Handler)
    print(f"GovIntel review dashboard: http://{args.host}:{args.port} (local-only; Ctrl+C to stop)")
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nDashboard stopped.")
    finally: server.server_close()


if __name__ == "__main__":
    main()

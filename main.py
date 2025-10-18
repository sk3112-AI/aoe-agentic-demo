import requests
from bs4 import BeautifulSoup
import time
import json
from fastapi import FastAPI, Request, Response, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from datetime import datetime
import logging
import sys
from openai import OpenAI
import uuid
from supabase import create_client, Client
import urllib.parse # ADDED: For URL encoding tracking links
import os, re, hmac, hashlib, json, time, base64
from datetime import datetime, timedelta, timezone
import httpx
import asyncio
from urllib.parse import quote_plus

# --- Lead score helper (single source of truth) ---
def _label_from_numeric(score: int) -> str:
    return "Hot" if score >= 10 else ("Warm" if score >= 5 else "Cold")

# Load environment variables (keep this for local development, Render handles env vars directly)
load_dotenv()

# Logging setup
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI()

# Supabase config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logging.error("Supabase URL or Key environment variables are not set.")
    raise ValueError("Supabase credentials not found. Please set SUPABASE_URL and SUPABASE_KEY in your .env file or Render environment.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
SUPABASE_TABLE_NAME = "bookings" # Ensure this matches your table name in Supabase

WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "")
WA_APP_SECRET        = os.getenv("WA_APP_SECRET", "")
WA_PHONE_NUMBER_ID   = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_TOKEN             = os.getenv("WA_TOKEN", "")
TRACKING_SIGNING_KEY = os.getenv("TRACKING_SIGNING_KEY", "")
TRACKING_BASE_URL    = os.getenv("TRACKING_BASE_URL", "").rstrip("/") + "/"
WA_USE_TEMPLATE      = os.getenv("WA_USE_TEMPLATE", "false").lower() == "true"
WA_TEMPLATE_NAME     = os.getenv("WA_TEMPLATE_NAME", "bind_request_v1")
WA_TEMPLATE_LANG     = os.getenv("WA_TEMPLATE_LANG", "en")

GRAPH_SEND_URL = f"https://graph.facebook.com/v24.0/{WA_PHONE_NUMBER_ID}/messages"
E164 = re.compile(r"^\+\d{7,15}$")

# --- HARDCODED VEHICLE DATA ---
# This dictionary replaces the web scraping logic for vehicle data.
AOE_VEHICLE_DATA = {
    "AOE Apex": {
        "type": "Luxury Sedan",
        "powertrain": "Gasoline",
        "features": "Premium leather interior, Advanced driver-assistance systems (ADAS), Panoramic sunroof, Bose premium sound system, Adaptive cruise control, Lane-keeping assist, Automated parking, Heated and ventilated seats."
    },
    "AOE Volt": {
        "type": "Electric Compact",
        "powertrain": "Electric",
        "features": "Long-range battery (500 miles), Fast charging (80% in 20 min), Regenerative braking, Solar roof charging, Vehicle-to-Grid (V2G) capability, Digital cockpit, Over-the-air updates, Extensive charging network access."
    },
    "AOE Thunder": {
        "type": "Performance SUV",
        "powertrain": "Gasoline",
        "features": "V8 Twin-Turbo Engine, Adjustable air suspension, Sport Chrono Package, High-performance braking system, Off-road capabilities, Torque vectoring, 360-degree camera, Ambient lighting, Customizable drive modes."
    },
    "AOE Aero": {
        "type": "Hybrid Crossover",
        "powertrain": "Hybrid",
        "features": "Fuel-efficient hybrid system, All-wheel drive, Spacious cargo, Infotainment with large touchscreen, Wireless charging, Hands-free power liftgate, Remote start, Apple CarPlay/Android Auto."
    },
    "AOE Stellar": {
        "type": "Electric Pickup Truck",
        "powertrain": "Electric",
        "features": "Quad-motor AWD, 0-60 mph in 3 seconds, 10,000 lbs towing capacity, Frunk (front trunk) storage, Integrated air compressor, Worksite power outlets, Customizable bed configurations, Off-road driving modes."
    }
}

# --- REMOVED: Global variables for cached_aoe_vehicles_data, LAST_DATA_REFRESH_TIME, REFRESH_INTERVAL_SECONDS ---
# --- REMOVED: fetch_aoe_vehicle_data_from_website() function ---
# --- REMOVED: scrape_aoe_vehicles_data() function and its initial call ---


# Email configuration
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 465)) # Default to 465 for SSL

# Team Email for notifications
TEAM_EMAIL = os.getenv("TEAM_EMAIL")

# ADDED: Tracking URL from environment variables
TRACKING_URL = os.getenv("TRACKING_URL")
if not TRACKING_URL:
    logging.warning("TRACKING_URL environment variable is not set. Email open/click tracking will be disabled.")


# OpenAI Client setup
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = None
if OPENAI_API_KEY:
    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        logging.error(f"Failed to initialize OpenAI client: {e}", exc_info=True)
        openai_client = None # Ensure it's None if init fails
else:
    logging.warning("OPENAI_API_KEY environment variable is not set. AI functionalities will be limited.")


def get_vehicle_resources(vehicle_name: str):
    """
    Returns mock resource links (YouTube, PDF) for a given vehicle.
    In a real application, this would fetch from a database or API.
    """
    resources = {
        "AOE Apex": { # Updated to full name
            "youtube_link": "https://www.youtube.com/watch?v=aoe_apex_overview",
            "pdf_link": "https://www.aoemotors.com/docs/apex_guide.pdf"
        },
        "AOE Volt": { # Updated to full name
            "youtube_link": "https://www.youtube.com/watch?v=aoe_volt_review",
            "pdf_link": "https://www.aoemotors.com/docs/volt_specs.pdf"
        },
        "AOE Thunder": { # Added full name
            "youtube_link": "https://www.youtube.com/watch?v=aoe_thunder_power",
            "pdf_link": "https://www.aoemotors.com/docs/thunder_brochure.pdf"
        },
        "AOE Aero": { # Added full name
            "youtube_link": "https://www.youtube.com/watch?v=aoe_aero_features",
            "pdf_link": "https://www.aoemotors.com/docs/aero_brochure.pdf"
        },
        "AOE Stellar": { # Added full name
            "youtube_link": "https://www.youtube.com/watch?v=aoe_stellar_reveal",
            "pdf_link": "https://www.aoemotors.com/docs/stellar_specs.pdf"
        }
    }
    return resources.get(vehicle_name, {
        "youtube_link": "https://www.youtube.com/watch?v=aoe_generic_overview",
        "pdf_link": "https://www.aoemotors.com/docs/generic_guide.pdf"
    })

# CORS configuration to allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows all origins
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"], # Allows all headers
)

# -------------------- Supabase helpers (generic) --------------------
def _sb_hdr(json_body=False):
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    if json_body:
        h["Content-Type"] = "application/json"
    return h

def _encode_eq(eq: dict) -> str:
    # URL-encode each value, so "+919..." becomes "%2B919..."
    return "&".join(f"{k}=eq.{quote_plus(str(v))}" for k, v in eq.items())

async def sb_select_one(table: str, eq: dict, select: str="*") -> Optional[dict]:
    params = {"select": select, "limit": 1}
    for k, v in eq.items():
        params[k] = f"eq.{v}"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=_sb_hdr(), params=params)
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=r.text)
    data = r.json()
    return data[0] if data else None


async def sb_select(table: str, filters: dict | None = None, select: str = "*",
                    order: str | None = None, limit: int | None = None):
    params = {"select": select}
    if order: params["order"] = order
    if limit: params["limit"] = limit
    if filters:
        # encode each filter value
        for k, v in filters.items():
            params[k] = f"eq.{quote_plus(str(v))}"

    url = f"{SUPABASE_URL}/rest/v1/{table}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=_sb_hdr(), params=params)
        r.raise_for_status()
        return r.json()

async def sb_insert(table: str, row: dict):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(url, headers={**_sb_hdr(True), "Prefer":"return=representation"}, json=row)
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=r.text)
    return r.json()

async def sb_upsert(table: str, row: dict, conflict: str):
    url = f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={conflict}"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(url, headers={**_sb_hdr(True),"Prefer":"resolution=merge-duplicates,return=representation"}, json=row)
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=r.text)
    return r.json()

async def upsert_conversation_on_bind(rid: str, wa_id: str):
    # called when you bind on button click
    now = datetime.utcnow().isoformat() + "Z"
    payload = {
        "conversation_id": rid,
        "request_id": rid,
        "wa_id": wa_id,
        "started_at": now,
        "last_message_at": now,
        "message_count": 1,
        "last_direction": "system"
    }
    await sb_upsert("wa_conversations", payload, conflict="conversation_id")

async def upsert_conversation_on_inbound(rid: str | None, wa_id: str):
    if not rid:
        return
    now = datetime.utcnow().isoformat() + "Z"
    # Light update; if you want message_count increments, do it in n8n or via RPC
    await sb_upsert("wa_conversations", {
        "conversation_id": rid,
        "request_id": rid,
        "wa_id": wa_id,
        "last_message_at": now,
        "last_direction": "inbound"
    }, conflict="conversation_id")

# -------------------- utils --------------------
import re
E164_RE = re.compile(r"^\+\d{7,15}$")

def to_e164(raw: str | None) -> str | None:
    if not raw: return None
    digits = re.sub(r"[^\d+]", "", raw)
    if not digits.startswith("+"):
        digits = "+" + re.sub(r"[^\d]", "", digits)
    return digits if E164_RE.match(digits) else None

def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")

def _u64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def make_token(payload: dict) -> str:
    body = json.dumps(payload, separators=(",",":"), ensure_ascii=False).encode()
    sig  = hmac.new(TRACKING_SIGNING_KEY.encode(), body, hashlib.sha256).digest()
    return f"{_b64u(body)}.{_b64u(sig)}"

def verify_token(token: str) -> dict:
    b64, s64 = token.split(".", 1)
    body, sig = _u64(b64), _u64(s64)
    good = hmac.new(TRACKING_SIGNING_KEY.encode(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, good):
        raise ValueError("bad signature")
    data = json.loads(body)
    if "exp" in data and int(time.time()) > int(data["exp"]):
        raise ValueError("expired")
    return data

def build_tracked(url: str | None, rid: str, wa_id: str, kind: str = "wa_resource", ttl_days: int = 7) -> str | None:
    if not url:
        return None
    exp = int(time.time()) + ttl_days * 86400
    token = make_token({"rid": rid, "wa_id": wa_id, "url": url, "kind": kind, "exp": exp})
    base = (TRACKING_BASE_URL or "").rstrip("/") + "/"
    return f"{base}t/{token}"

async def fetch_kb_links(model_key: str) -> dict | None:
    """
    Collect brochure/video links for a given model_key from faq_kb.
    The table has one row per intent (e.g., brochure, video, specs...),
    so we scan the set and pick the first non-empty links.
    """
    # If you have a generic "sb_select" that returns a list, use it; otherwise
    # call your existing select with an appropriate limit and no "one" semantics.
    rows = await sb_select(
        "faq_kb",
        {"model_key": model_key},
        select="intent, brochure_url, video_url"
    )

    out = {}
    for r in rows or []:
        # Prefer explicit fields shown in your table
        if not out.get("video_url") and r.get("video_url"):
            out["video_url"] = r["video_url"]
        if not out.get("pdf_url") and r.get("brochure_url"):
            out["pdf_url"] = r["brochure_url"]

    return out or None

async def sb_select(table: str, filters: dict | None = None, select: str = "*", order: str | None = None, limit: int | None = None):
    """
    Returns a list of rows (unlike sb_select_one).
    """
    params = {"select": select}
    if order:
        params["order"] = order
    if limit:
        params["limit"] = limit
    if filters:
        for k, v in filters.items():
            params[k] = f"eq.{v}"

    url = f"{SUPABASE_URL}/rest/v1/{table}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=_sb_hdr(), params=params)
        r.raise_for_status()
        return r.json()

# -------------------- WA send helpers --------------------
def canonical_model_key(raw: str) -> str:
    v = (raw or "").lower().strip()
    if "thunder" in v: return "AOE Thunder"
    if "apex"    in v: return "AOE Apex"
    if "volt"    in v: return "AOE Volt"
    # add mappings as you add models; fallback returns original
    return (raw or "").strip()

async def wa_send_text(wa_id: str, text: str) -> str:
    payload = {"messaging_product":"whatsapp","to":wa_id,"type":"text","text":{"body":text[:4096]}}
    headers = {"Authorization": f"Bearer {WA_TOKEN}","Content-Type":"application/json"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(GRAPH_SEND_URL, headers=headers, json=payload)
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=r.text)
    return (r.json().get("messages") or [{}])[0].get("id") or ""

async def wa_send_session_button(wa_id: str, text: str) -> str:
    payload = {
        "messaging_product":"whatsapp","to":wa_id,"type":"interactive",
        "interactive":{"type":"button","body":{"text":text[:1024]},
            "action":{"buttons":[{"type":"reply","reply":{"id":"bind_now","title":"Reply"}}]}}
    }
    headers = {"Authorization": f"Bearer {WA_TOKEN}","Content-Type":"application/json"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(GRAPH_SEND_URL, headers=headers, json=payload)
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=r.text)
    return (r.json().get("messages") or [{}])[0].get("id") or ""

async def wa_send_template_bind(wa_id: str, name: str|None, vehicle: str|None, date: str|None) -> str:
    payload = {
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": "template",
        "template": {
            "name": WA_TEMPLATE_NAME,
            "language": {"code": WA_TEMPLATE_LANG},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type":"text","text": name or "there"},
                    {"type":"text","text": vehicle or "your request"},
                    {"type":"text","text": date or ""}
                ]
            }]
        }
    }
    headers = {"Authorization": f"Bearer {WA_TOKEN}","Content-Type":"application/json"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(GRAPH_SEND_URL, headers=headers, json=payload)
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=r.text)
    return (r.json().get("messages") or [{}])[0].get("id") or ""

async def _kick_wa_session(rid: str):
    try:
        # Call the same logic your route uses
        await wa_session_start_by_rid({"request_id": rid})
    except Exception as e:
        logging.exception("WA kickoff failed for %s: %s", rid, e)

async def append_rolling_summary(rid: str, delta: str):
    """
    Appends a short delta into wa_conversations.rolling_summary
    Key assumption: conversation_id == request_id  (change here if not).
    """
    # 1) read current conversation
    conv = await sb_select_one("wa_conversations", {"conversation_id": rid}, select="rolling_summary")
    cur = (conv or {}).get("rolling_summary") or ""

    # 2) append + trim
    new_rs = (cur + " " + delta).strip() if cur else delta
    if len(new_rs) > 2000:
        new_rs = ("..." + new_rs[-1997:])  # simple tail-trim for demo

    # 3) upsert conversation
    # (if conversation row may not exist yet, this upsert creates it)
    payload = {
        "conversation_id": rid,       # change if your PK is different
        "rolling_summary": new_rs,
        "updated_at": datetime.utcnow().isoformat() + "Z"
    }
    await sb_upsert("wa_conversations", payload, conflict="conversation_id")


# --- DEBUG LOGGING ENDPOINT ---
@app.get("/debug-logs")
async def get_debug_logs():
    """Endpoint to retrieve recent debug logs."""
    logging.info("Debug logs requested.")
    return {"message": "Debug logging is active. Check server console for full logs."}
# --- END DEBUG LOGGING ---


@app.get("/")
async def read_root():
    """Root endpoint for the API."""
    return {"message": "Welcome to AOE Motors Test Drive API. Send a POST request to /webhook/testdrive to book a test drive."}

# EXISTING ENDPOINT FOR VEHICLE DATA - NOW SERVING HARDCODED DATA
@app.get("/vehicles-data")
async def get_vehicles_data():
    """
    Endpoint to retrieve hardcoded AOE Motors vehicle data.
    """
    try:
        # Directly return the hardcoded data
        return AOE_VEHICLE_DATA
    except Exception as e:
        logging.error(f"❌ Error retrieving vehicle data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve vehicle data.")

# NEW ENDPOINT 1: Update Booking Status and Sales Notes
class UpdateBookingRequest(BaseModel):
    request_id: str
    action_status: Optional[str] = None
    sales_notes: Optional[str] = None
    # NEW:
    numeric_lead_score: Optional[int] = None
    lead_score: Optional[str] = None   # text label (Hot/Warm/Cold); backend can auto-derive if omitted
    # (optional, if you want snooze metadata later)
    wait_until: Optional[str] = None   # ISO 8601 string, e.g. "2025-09-10T10:00:00Z"

@app.post("/update-booking")
async def update_booking(request_body: UpdateBookingRequest):
    """
    Endpoint to update a booking's action_status and sales_notes in Supabase.
    """
    try:
        update_data = {}
        if request_body.action_status is not None:
            update_data["action_status"] = request_body.action_status

        if request_body.sales_notes is not None:
            update_data["sales_notes"] = request_body.sales_notes

        if request_body.numeric_lead_score is not None:
            n = request_body.numeric_lead_score
            update_data["numeric_lead_score"] = n
            # If caller didn’t send the label, derive it with your existing thresholds
        if request_body.lead_score is None:
            update_data["lead_score"] = _label_from_numeric(n)

        # If caller sent an explicit text label, honor it
        if request_body.lead_score is not None:
            update_data["lead_score"] = request_body.lead_score

        # Optional snooze timestamp (for future use)
        if request_body.wait_until is not None:
            update_data["wait_until"] = request_body.wait_until

        if not update_data:
            raise HTTPException(status_code=400, detail="No updatable fields provided.")

        resp = supabase.from_(SUPABASE_TABLE_NAME).update(update_data).eq("request_id", request_body.request_id).execute()

        if resp.data:
            logging.info(f"Updated {request_body.request_id}: {update_data}")
            return {"status": "success", "data": resp.data}
        raise HTTPException(status_code=500, detail="Failed to update booking.")
    except Exception as e:
        logging.error(f"Error updating booking {request_body.request_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")
           

# NEW ENDPOINT 2: Draft and Send Follow-up Email
class DraftAndSendEmailRequest(BaseModel):
    customer_name: str
    customer_email: str
    vehicle_name: str
    sales_notes: str
    vehicle_details: dict # Pass the relevant vehicle details from frontend

@app.get("/wa/webhook")
async def wa_verify(
    mode: str | None = Query(None, alias="hub.mode"),
    verify_token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
):
    # must return the raw challenge string when token matches
    if mode == "subscribe" and verify_token == os.getenv("WEBHOOK_VERIFY_TOKEN", ""):
        return Response(content=challenge or "", media_type="text/plain")
    return Response(content="forbidden", status_code=403)


@app.post("/draft-and-send-followup-email")
async def draft_and_send_followup_email(request_body: DraftAndSendEmailRequest):
    """
    Endpoint to draft an AI email based on sales notes and send it to the customer.
    """
    logging.info(f"Received request to draft and send email for {request_body.customer_name}.")

    try:
        features_str = request_body.vehicle_details.get("features", "cutting-edge technology and a luxurious experience.")
        vehicle_type = request_body.vehicle_details.get("type", "vehicle")
        powertrain = request_body.vehicle_details.get("powertrain", "advanced performance")

        # This prompt is for drafting the email using OpenAI
        # For this function, the AI response needs to be structured as a valid email body only.
        prompt = f"""
        Draft a polite, helpful, and persuasive follow-up email to a customer named {request_body.customer_name}.

        **Customer Information:**
        - Name: {request_body.customer_name}
        - Email: {request_body.customer_email}
        - Vehicle of Interest: {request_body.vehicle_name} ({vehicle_type}, {powertrain} powertrain)
        - Customer Issues/Comments (from sales notes): "{request_body.sales_notes}"

        **AOE {request_body.vehicle_name} Key Features:**
        - {features_str}

        **Email Instructions:**
        - Start with a polite greeting.
        - Acknowledge their recent interaction (e.g., test drive, inquiry).
        - **Crucial:** **ABSOLUTELY DO NOT include the subject line or any "Subject:" prefix in the email body.**
        - **STRICT Formatting Output Rules (MUST use HTML <p> tags):**
            * **The entire email body MUST be composed of distinct HTML paragraph tags (`<p>...</p>`).**
            * **Each logical section/paragraph MUST be entirely enclosed within its own `<p>` and `</p>` tags.**
            * **Each paragraph (`<p>...</p>`) should be concise (typically 2-4 sentences maximum).**
            * **Aim for a total of 4-6 distinct HTML paragraphs.**
            * **DO NOT use `\\n\\n` for spacing; the `<p>` tags provide the necessary visual separation.**
            * **DO NOT include any section dividers (like '---').**
            * **Ensure there is no extra blank space before the first `<p>` tag or after the last `</p>` tag.**
            * **Output the email body in valid HTML format.**

        **Content Structure & Logic (Each point should be a distinct HTML paragraph):**

        * **Paragraph 1 (Greeting & Acknowledgment):**
            * Polite greeting to {request_body.customer_name}.
            * Acknowledge their recent interaction or interest in the {request_body.vehicle_name}.

        * **Paragraph 2 (Key Features & Benefits):**
            * Highlight 2-3 most relevant and exciting features of the {request_body.vehicle_name} based on the provided {features_str}.
            * Translate technical terms into clear benefits for the driver.
            * Mention the vehicle type ({vehicle_type}) and powertrain ({powertrain}).

        * **Paragraph 3 (Address Sales Notes/Concerns):**
            * Directly and helpfully address the points raised in {request_body.sales_notes}.
            * Offer solutions or further information related to their specific comments.

        * **Paragraph 4 (Call to Action & Next Steps):**
            * Encourage further engagement (e.g., schedule another call, visit showroom, answer more questions).
            * Reinforce readiness to assist them.

        * **Paragraph 5 (Closing):**
            * End with a polite closing like "Warm regards, Team AOE Motors".
        """
        body_completion = openai_client.chat.completions.create(
            model="gpt-3.5-turbo", # You can choose a different model like "gpt-4o" for better quality if available and cost allows
            messages=[
                {"role": "system", "content": "You are a helpful assistant for AOE Motors, crafting personalized, persuasive, human-like, and well-formatted follow-up emails. Your output MUST be in HTML format using <p> tags for paragraphs. You must be absolutely factually accurate about vehicle type and powertrain as provided."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        generated_body = body_completion.choices[0].message.content.strip()
        logging.debug(f"Generated Body (partial): {generated_body[:100]}...")

        # For follow-up emails, a generic but professional subject line.
        generated_subject = f"Following Up on Your Interest in the AOE {request_body.vehicle_name}"

        # --- Email Sending Logic ---
        if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD]):
            raise ValueError("One or more email configuration environment variables are missing or empty.")

        msg_customer = MIMEMultipart("alternative")
        msg_customer["From"] = EMAIL_ADDRESS
        msg_customer["To"] = request_body.customer_email
        msg_customer["Subject"] = generated_subject
        msg_customer.add_header("Reply-To", f"aoereplies+{request_id}@gmail.com")
        msg_customer.attach(MIMEText(generated_body, "html")) # Explicitly using 'html' to interpret <p> tags

        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
            logging.debug(f"Attempting to connect to SMTP server for follow-up email: {EMAIL_HOST}:{EMAIL_PORT}")
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg_customer)
            logging.info(f"✅ Follow-up email successfully sent to {request_body.customer_email} (Subject: '{generated_subject}').")

        return {"status": "success", "message": "Follow-up email drafted and sent successfully."}

    except Exception as e:
        logging.error(f"🚨 An unexpected error occurred during follow-up email processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

# -------------------- Webhook: POST (events) --------------------
@app.post("/wa/webhook")
async def wa_events(request: Request):
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature-256","")
    if WA_APP_SECRET:
        digest = hmac.new(WA_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, f"sha256={digest}"):
            raise HTTPException(status_code=401, detail="bad signature")

    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            v = change.get("value", {})

            for m in v.get("messages", []) or []:
                mtype = m.get("type")
                from_ = m.get("from")
                wa_id  = f"+{from_}" if from_ and not str(from_).startswith("+") else from_
                mid    = m.get("id")

                # A) Interactive reply (button) -> bind
                if mtype in ("interactive","button"):
                    ctx_id = (m.get("context") or {}).get("id")
                    rid = None
                    if ctx_id:
                        row = await sb_select_one("wa_outbound_log", {"message_id": ctx_id}, select="request_id")
                        if row:
                            rid = row["request_id"]

                    if rid and wa_id:
                        now = datetime.now(timezone.utc)
                        exp = now + timedelta(hours=48)
                        await sb_upsert("wa_request_links", {
                            "wa_id": wa_id, "request_id": rid, "active": True,
                            "bound_at": now.isoformat(), "expires_at": exp.isoformat(),
                            "bound_via": "button"
                        }, conflict="wa_id")

                        # Confirmation
                        text = "Thanks! I’ve linked this WhatsApp chat to your request. I’ll follow up here."
                        out_id = await wa_send_text(wa_id, text)

                        await sb_insert("wa_messages", {
                            "message_id": mid, "request_id": rid, "wa_id": wa_id,
                            "direction": "inbound",
                            "body_text": (m.get("interactive") or {}).get("button_reply", {}).get("title") or "Reply"
                        })
                        if out_id:
                            await sb_insert("wa_messages", {
                                "message_id": out_id, "request_id": rid, "wa_id": wa_id,
                                "direction": "outbound", "body_text": text
                            })

                        # --- FOLLOW-UP START ---
                        # Requires helpers: fetch_kb_links(), build_tracked(), append_rolling_summary()
                                    # simple follow-up
                        try:
                            b = await sb_select_one(SUPABASE_TABLE_NAME, {"request_id": rid}, select="full_name")
                            first = ((b or {}).get("full_name") or "").split(" ")[0]
                            followup_text = f"Thank you{', ' + first if first else ''}! Your test drive is confirmed. Please let me know if you have any questions."
                            fu_id = await wa_send_text(wa_id, followup_text)
                            if fu_id:
                                await sb_insert("wa_messages", {
                                    "message_id": fu_id, "request_id": rid, "wa_id": wa_id,
                                    "direction": "outbound", "body_text": followup_text
                                })
                            await append_rolling_summary(rid, "WA: chat bound and follow-up sent.")
                        except Exception as e:
                            logging.warning(f"Follow-up WA message failed for {rid}: {e}")

                        # optional: notify n8n that session is bound
                        try:
                            await _notify_n8n({"event":"session_bound","request_id":rid,"wa_id":wa_id,"message_id":mid})
                        except Exception:
                            pass

                    else:
                        await sb_insert("wa_messages", {
                            "message_id": mid, "request_id": None, "wa_id": wa_id,
                            "direction": "inbound", "body_text": "Reply (unmapped)", "payload": m
                        })
                    continue

                # B) Inbound text -> log and handoff
                elif mtype == "text":
                    txt = (m.get("text") or {}).get("body", "")
                    bind = await sb_select_one("wa_request_links", {"wa_id": wa_id}, select="request_id, active, expires_at")
                    rid = bind["request_id"] if bind and bind.get("active") else None

                    await sb_insert("wa_messages", {
                        "message_id": mid, "request_id": rid, "wa_id": wa_id,
                        "direction": "inbound", "body_text": txt, "payload": m
                    })
                    await upsert_conversation_on_inbound(rid, wa_id)

                    # push to n8n as a normal user message
                    try:
                        await _notify_n8n({"event":"inbound_text","request_id":rid,"wa_id":wa_id,"text":txt,"message_id":mid})
                    except Exception:
                        pass
                    continue                     
    return {"ok": True}

# -------------------- Start session message (manual wa_id) --------------------
class SessionKickoff(BaseModel):
    request_id: str
    wa_id: str
    name: str | None = None
    vehicle: str | None = None
    date: str | None = None

@app.post("/wa/session_start")
async def wa_session_start(p: SessionKickoff):
    if not E164.match(p.wa_id):
        raise HTTPException(status_code=400, detail="wa_id must be E.164 (+country...)")
    text = f"Hi {p.name or 'there'} — re: {p.vehicle or 'your request'}" + (f" on {p.date}" if p.date else "") + ". Tap Reply to continue here."
    if WA_USE_TEMPLATE:
        msg_id = await wa_send_template_bind(p.wa_id, p.name, p.vehicle, p.date)
        marker = WA_TEMPLATE_NAME
    else:
        msg_id = await wa_send_session_button(p.wa_id, text)
        marker = "session_button"

    await sb_insert("wa_outbound_log", {"message_id": msg_id, "wa_id": p.wa_id, "request_id": p.request_id, "template_name": marker})
    await sb_insert("wa_messages", {"message_id": msg_id, "request_id": p.request_id, "wa_id": p.wa_id, "direction": "outbound", "body_text": text if not WA_USE_TEMPLATE else None})
    return {"ok": True, "message_id": msg_id}

# -------------------- Start session by request_id (reads phone from BOOKINGS) --------------------
@app.post("/wa/session_start_by_rid")
async def wa_session_start_by_rid(payload: dict):
    rid = payload.get("request_id")
    if not rid:
        raise HTTPException(status_code=400, detail="request_id required")

    # *** HERE we use SUPABASE_TABLE_NAME instead of hard-coded 'bookings' ***
    row = await sb_select_one(SUPABASE_TABLE_NAME, {"request_id": rid}, select="request_id, full_name, phone, vehicle, booking_date")
    if not row:
        raise HTTPException(status_code=404, detail="booking not found")

    wa_id = to_e164(row.get("phone"))
    if not wa_id:
        raise HTTPException(status_code=400, detail="no usable phone for this request")

    name, vehicle = row.get("full_name"), row.get("vehicle")
    date = row.get("booking_date") or ""
    text = f"Hi {name or 'there'} — re: {vehicle or 'your request'}" + (f" on {date}" if date else "") + ". Tap Reply to continue here."

    if WA_USE_TEMPLATE:
        msg_id = await wa_send_template_bind(wa_id, name, vehicle, date)
        marker = WA_TEMPLATE_NAME
    else:
        msg_id = await wa_send_session_button(wa_id, text)
        marker = "session_button"

    await sb_insert("wa_outbound_log", {"message_id": msg_id, "wa_id": wa_id, "request_id": rid, "template_name": marker})
    await sb_insert("wa_messages", {"message_id": msg_id, "request_id": rid, "wa_id": wa_id, "direction": "outbound", "body_text": text if not WA_USE_TEMPLATE else None})
    return {"ok": True, "message_id": msg_id, "wa_id": wa_id}

# -------------------- Generic send text (for n8n) --------------------
class SendTextPayload(BaseModel):
    request_id: Optional[str] = None
    wa_id: str
    text: str
# If not already imported:
# from pydantic import BaseModel

class SendAndSummarize(BaseModel):
    request_id: str           # usually your request_id / conversation_id
    wa_id: str                # E.164 like +91...
    text: str                 # message to send
    summary_delta: str | None = None  # optional extra summary line
    action_status: str | None = None  # optional, to update bookings.action_status

class RollingSummaryUpdate(BaseModel):
    request_id: str
    delta: str

@app.post("/wa/send_text_and_summarize")
async def wa_send_text_and_summarize(p: SendAndSummarize):
    if not E164.match(p.wa_id):
        raise HTTPException(status_code=400, detail="wa_id must be E.164")
    out_id = await wa_send_text(p.wa_id, p.text)
    await sb_insert("wa_messages", {
        "message_id": out_id, "request_id": p.request_id, "wa_id": p.wa_id,
        "direction": "outbound", "body_text": p.text
    })
    # Update wa_conversations
    delta = p.summary_delta or f"WA bot reply: “{p.text[:160]}”"
    await append_rolling_summary(p.request_id, delta)

    # optional action_status on your bookings table (keep if you still use it)
    if p.action_status:
        try:
            await sb_upsert(SUPABASE_TABLE_NAME, {"request_id": p.request_id, "action_status": p.action_status}, conflict="request_id")
        except Exception:
            pass
    return {"ok": True, "message_id": out_id}

@app.post("/rolling_summary/append")
async def api_append_rolling_summary(p: RollingSummaryUpdate):
    await append_rolling_summary(p.request_id, p.delta)
    return {"ok": True}

@app.post("/wa/send_text")
async def api_send_text(p: SendTextPayload):
    if not E164.match(p.wa_id):
        raise HTTPException(status_code=400, detail="wa_id must be E.164")
    out_id = await wa_send_text(p.wa_id, p.text)
    await sb_insert("wa_messages", {"message_id": out_id, "request_id": p.request_id, "wa_id": p.wa_id, "direction": "outbound", "body_text": p.text})
    return {"ok": True, "message_id": out_id}

# -------------------- Tracked-link redirect --------------------
@app.get("/t/{token}")
async def track_and_redirect(token: str):
    try:
        data = verify_token(token)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        await sb_insert("link_clicks", {"token": token, "request_id": data.get("rid"), "wa_id": data.get("wa_id")})
    except Exception:
        pass
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="no url")
    return Response(status_code=302, headers={"Location": url})
# ORIGINAL WEBHOOK ENDPOINT: Process incoming test drive requests
@app.post("/webhook/testdrive")
async def testdrive_webhook(request: Request):
    """
    Webhook endpoint to receive test drive requests.
    Processes the request, generates an AI email, sends notifications, and saves data.
    """
    try:
        data = await request.json()
        logging.info(f"Received webhook data: {data}")

        # Extract data from the incoming request - CORRECTED KEYS for camelCase
        full_name = data.get("fullName")
        email = data.get("email")
        vehicle = data.get("vehicle")
        date = data.get("date") # This isYYYY-MM-DD
        location = data.get("location")
        current_vehicle = data.get("currentVehicle")
        time_frame = data.get("timeFrame")
        phone_raw = data.get("phone")  # e.g. "+919876543210"
        phone_e164 = to_e164(phone_raw)

        if not all([full_name, email, vehicle, date, location, current_vehicle, time_frame]):
            raise HTTPException(status_code=400, detail="Missing required test drive booking fields.")

        request_id = str(uuid.uuid4()) # Generate a unique request ID

        # Format date for display
        try:
            formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%B %d, %Y")
        except ValueError:
            formatted_date = date # Fallback if date format is unexpected

        # Retrieve detailed vehicle info from hardcoded data
        vehicle_info = AOE_VEHICLE_DATA.get(vehicle)
        if not vehicle_info:
            logging.warning(f"Vehicle '{vehicle}' not found in hardcoded data.")
            vehicle_type = "N/A"
            powertrain_type = "N/A"
            chosen_aoe_features = "no specific features available"
        else:
            vehicle_type = vehicle_info.get("type", "N/A")
            powertrain_type = vehicle_info.get("powertrain", "N/A")
            chosen_aoe_features = vehicle_info.get("features", "no specific features available")

        # Get resource links
        resources = get_vehicle_resources(vehicle)
        # Original links - these are now used to construct tracking links
        original_youtube_link = resources["youtube_link"]
        original_pdf_link = resources["pdf_link"]

        # --- Tracking Setup (ADDED) ---
        # Ensure TRACKING_URL is imported/defined globally and holds the Edge Function URL
        # For simplicity in this block, assuming TRACKING_URL is accessible here
        # If not already done, add TRACKING_URL = os.getenv("TRACKING_URL") at the global email config section.
        tracking_pixel_html = ""
        trackable_youtube_link = original_youtube_link # Default to original if no tracking
        trackable_pdf_link = original_pdf_link # Default to original if no tracking

        if TRACKING_URL:
            # URL-encode the original links for the redirect_to parameter
            encoded_youtube_link = urllib.parse.quote_plus(original_youtube_link)
            encoded_pdf_link = urllib.parse.quote_plus(original_pdf_link)

            # Create tracking URLs using the Edge Function endpoint
            trackable_youtube_link = f"{TRACKING_URL}?request_id={request_id}&event_type=clicked_video&redirect_to={encoded_youtube_link}"
            trackable_pdf_link = f"{TRACKING_URL}?request_id={request_id}&event_type=clicked_pdf&redirect_to={encoded_pdf_link}"

            # Tracking pixel HTML, hidden
            tracking_pixel_html = f'<img src="{TRACKING_URL}?request_id={request_id}&event_type=opened" width="1" height="1" style="display:none;">'
        else:
            logging.warning("TRACKING_URL is not set, email open/click tracking will not be active for this email.")
        # --- END Tracking Setup ---


        # --- AI Email Generation (Customer) ---
        logging.info(f"Generating AI email for customer: {email}")
        body_prompt = f"""
        Draft a polite, helpful, and persuasive test drive confirmation email to a customer named {full_name}.

        **Customer Information:**
        - Name: {full_name}
        - Email: {email}
        - Vehicle: {vehicle} ({vehicle_type}, {powertrain_type} powertrain)
        - Test Drive Date: {formatted_date}
        - Test Drive Location: {location}
        - Current Vehicle: {current_vehicle}
        - Purchase Time Frame: {time_frame}

        **AOE {vehicle} Key Features:**
        - {chosen_aoe_features}

        **Additional Resources:**
        - YouTube Link: {trackable_youtube_link} # Now using trackable link
        - PDF Link: {trackable_pdf_link} # Now using trackable link

        **Email Instructions:**
        - Start with a polite greeting.
        - Confirm the test drive details (vehicle, date, location) immediately, emphasizing excitement.
        - **Crucial:** **ABSOLUTELY DO NOT include the subject line or any "Subject:" prefix in the email body.**
        - **STRICT Formatting Output Rules (MUST use HTML <p> tags):**
            * **The entire email body MUST be composed of distinct HTML paragraph tags (`<p>...</p>`).**
            * **Each logical section/paragraph MUST be entirely enclosed within its own `<p>` and `</p>` tags.**
            * **Each paragraph (`<p>...</p>`) should be concise (typically 2-4 sentences maximum).**
            * **Aim for a total of 5-7 distinct HTML paragraphs.**
            * **DO NOT use `\\n\\n` for spacing; the `<p>` tags provide the necessary visual separation.**
            * **DO NOT include any section dividers (like '---').**
            * **Ensure there is no extra blank space before the first `<p>` tag or after the last `</p>` tag.**

        **Content Structure & Logic (Each point should be a distinct HTML paragraph):**

        * **Paragraph 1 (Greeting & Test Drive Confirmation):**
            * Polite greeting to {full_name}.
            * Confirm the test drive details (vehicle, date, location) immediately, emphasizing excitement.
            * Example: "<p>Dear {full_name},</p><p>We are thrilled to confirm your upcoming test drive of the {vehicle} on {formatted_date} in {location}. Get ready for an exhilarating experience!</p>"

        * **Paragraph 2 (Vehicle Features & Persuasive Comparison - Conditional Logic):**
            * **Based on `Current Vehicle` (use ONE of the following two patterns for this paragraph):**

            * **Pattern A: If `current_vehicle` is provided (and NOT 'No-vehicle' or 'exploring'):**
                * **YOU MUST start this paragraph by subtly positioning the {vehicle} as a significant, transformative upgrade compared to their current vehicle.**
                * **From the provided {chosen_aoe_features}, select 2-3 MOST EXCITING and UNIQUE features of the {vehicle} that highlight this upgrade.**
                * **Translate technical jargon into clear, simple benefits for the driver. AVOID using technical jargon directly if a simpler benefit can be stated.**
                * **Example:** "<p>As a {current_vehicle} owner, prepare to experience the next level of automotive innovation with the {vehicle} {vehicle_type}. Its [GENERATE 2-3 KEY FEATURES AND THEIR BENEFITS HERE, translating technical terms into clear, simple benefits for the driver, e.g., 'luxurious interior comfort and cutting-edge safety systems'] offer a remarkable {powertrain_type} driving experience that truly elevates beyond what you're accustomed to.</p>"
                * **Crucial:** Ensure this comparison is subtle and positive.

            * **Pattern B: If `current_vehicle` IS 'No-vehicle' or 'exploring':**
                * Frame it as an exciting new kind of driving experience, a leap into advanced {powertrain_type} {vehicle_type} technology, or an opportunity to discover what makes AOE Motors unique.
                * **From the provided {chosen_aoe_features}, select 2-3 MOST EXCITING and UNIQUE features of the {vehicle}.**
                * **Translate any technical jargon into clear, simple benefits for the driver. AVOID using technical jargon directly if a simpler benefit can be stated.**
                * **CRITICAL: DO NOT use terms like 'owner' or attempt ANY comparison to a previous vehicle in this scenario.**
                * **Example:** "<p>Prepare to be amazed by the {vehicle} {vehicle_type} with its [GENERATE 2-3 KEY FEATURES AND THEIR BENEFITS HERE, translating technical terms into clear, simple benefits for the driver, e.g., 'impressive range and rapid charging capabilities, alongside a sophisticated digital cockpit']. This {powertrain_type} vehicle redefines driving pleasure, offering a truly exhilarating and sophisticated experience.</p>"

        * **Paragraph 3 (Overall Experience & Broader Benefits - NO new features):**
            * This paragraph should focus on the *overall driving experience* of the {vehicle} or the * broader benefits* of choosing an AOE vehicle.
            * **Do NOT introduce any new specific features in this paragraph.** This paragraph is for a more general, appealing description.
            * If `current_vehicle` is 'exploring', this paragraph can reinforce the idea of discovery, reliability, and the unique possibilities the {vehicle} offers for their lifestyle.
            * Example: "<p>Beyond its impressive features, the {vehicle} is engineered for a harmonious blend of exhilarating performance and sophisticated comfort, ensuring every drive is a pleasure.</p>" (This is an example, LLM should adapt.)

        * **Paragraph 4 (Personalized Support for Your Journey - CRITICAL IMPLICIT FIX for 'exploring'):**
            * This paragraph will *exclusively* address the '{time_frame}' for *purchase intent*.
            * **CRITICAL: This paragraph MUST NOT explicitly mention '{time_frame}' or any specific timeframe (e.g., '0-3 months', '3-6 months', '6-12 months', 'exploring'). Convey the time frame *implicitly* through the tone and focus of the support offered, using phrasing that aligns with their readiness.**
            * **Do NOT use any phrasing that implies urgency or a swift decision for 'exploring'.**
            * If `time_frame` is '0-3-months': Emphasize AOE Motors' readiness to support their swift decision, hinting at tailored support and exclusive opportunities for those ready to embrace the future soon.
                * *Example Implicit Phrasing:* "We understand you're ready to make a swift decision, and our team is poised to offer tailored support and exclusive opportunities as you approach ownership."
            * If `time_frame` is '3-6-months' or '6-12-months': Focus on offering continued guidance and resources throughout their decision-making journey, highlighting that you're ready to assist them when they're closer to a purchase decision, providing resources for further exploration.
                * *Example Implicit Phrasing:* "As you carefully consider your options over the coming months, we are committed to providing comprehensive support and insights to help you make an informed choice."
            * If `time_frame` is 'exploring': Maintain a welcoming, low-pressure tone, focusing purely on discovery and making the experience informative and enjoyable for their future consideration, without any hint of urgency or swift decisions. The goal is to provide resources and be available for questions at their pace.
                * *Example Implicit Phrasing (stronger emphasis for 'exploring', and explicit negative constraint for LLM):* "We are delighted to support you at your own pace as you explore the possibilities. There's no pressure; our team is here to provide any information or answer any questions you may have as you consider your options for the future." **Absolutely avoid any phrasing like 'swift decision', 'ready to make a purchase', 'approach ownership', 'your purchase decision' for 'exploring' customers.**

        * **Paragraph 5 (Valuable Resources):**
            * **MUST generate a sentence encouraging them to learn more about the {vehicle}. Then, immediately follow with TWO distinct HTML hyperlinks.**
            * **The first hyperlink MUST be for the YouTube Link (`{trackable_youtube_link}`). Its link text MUST be "Watch the {vehicle} Overview Video".**
            * **The second hyperlink MUST be for the PDF Guide Link (`{trackable_pdf_link}`). Its link text MUST be "Download the {vehicle} Guide (PDF)".**
            * **CRITICAL: Ensure the link text for both links uses the exact `{vehicle}` value and does NOT add 'AOE' or any other brand name prefix again if it's already present in `{vehicle}`.**
            * **YOU MUST FOLLOW THIS HTML STRUCTURE for the entire paragraph:** `<p>To learn even more about the {vehicle}, we invite you to watch our detailed video and download the comprehensive guide: <a href="{trackable_youtube_link}">Watch the {vehicle} Overview Video</a> <a href="{trackable_pdf_link}">Download the {vehicle} Guide (PDF)</a></p>`

        * **Paragraph 6 (Call to Action & Closing):**
            * **MUST generate a clear and helpful call to action for any questions. Immediately follow with an expression of eagerness for their visit.**
            * **MUST end with "Warm regards, Team AOE Motors" within the SAME final paragraph's `<p>` tags.**
            * **YOU MUST FOLLOW THIS HTML STRUCTURE for the entire paragraph:** `<p>For any questions or further assistance, please do not hesitate to contact us. We eagerly await your visit! Warm regards, Team AOE Motors</p>`
        """
        body_completion = openai_client.chat.completions.create(
            model="gpt-3.5-turbo", # You can choose a different model like "gpt-4o" for better quality if available and cost allows
            messages=[
                {"role": "system", "content": "You are a helpful assistant for AOE Motors, crafting personalized, persuasive, human-like, and well-formatted test drive confirmation emails. Your output MUST be in HTML format using <p> tags for paragraphs. You must be absolutely factually accurate about vehicle type and powertrain as provided."},
                {"role": "user", "content": body_prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        generated_body = body_completion.choices[0].message.content.strip()
        logging.debug(f"Generated Body (partial): {generated_body[:100]}...")


        # --- Rule-Based Lead Scoring ---
        logging.info(f"Applying rule-based lead scoring for {email}...")
        
        initial_numeric_score = 0
        if time_frame == "0-3-months":
            initial_numeric_score = 10
        elif time_frame == "3-6-months":
            initial_numeric_score = 7
        elif time_frame == "6-12-months":
            initial_numeric_score = 5
        elif time_frame == "exploring-now": # CORRECTED: Changed from "exploring" to "exploring-now"
            initial_numeric_score = 2
        
        # Determine initial text lead_score based on numeric score
        lead_score_text = _label_from_numeric(initial_numeric_score)

        logging.info(f"Initial Numeric Lead Score for {email}: '{initial_numeric_score}', Text Status: '{lead_score_text}'")


        # --- Email Sending to Customer (rest of this section remains the same) ---
        generated_subject = f"AOE Test Drive Confirmed! Get Ready for Your {vehicle} Experience"
        if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD]):
            raise ValueError("One or more email configuration environment variables are missing or empty.")

        msg_customer = MIMEMultipart("alternative")
        msg_customer["From"] = EMAIL_ADDRESS
        msg_customer["To"] = email
        msg_customer["Subject"] = generated_subject
        msg_customer.add_header("Reply-To", f"aoereplies+{request_id}@gmail.com")
        msg_customer.attach(MIMEText(generated_body + tracking_pixel_html, "html")) # APPEND TRACKING PIXEL HERE
        # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ ADDED

        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
            logging.debug(f"Attempting to connect to SMTP server for customer email: {EMAIL_HOST}:{EMAIL_PORT}")
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg_customer)
            logging.info(f"✅ Customer email successfully sent to {email} (Subject: '{generated_subject}', Score: '{lead_score_text}').")

        # --- Email Sending to Team ---
        if TEAM_EMAIL and EMAIL_ADDRESS and EMAIL_PASSWORD: # Ensure TEAM_EMAIL is configured
            team_subject = f"New Test Drive Booking for {vehicle}" # Define team_subject here
            # Changed to .format() for robustness against nested f-string issues
            team_body = """
            Dear Team,

            A new test drive booking has been received.

            **Customer Details:**
            - Name: {full_name}
            - Email: {email}
            - Vehicle: {vehicle} (Type: {vehicle_type}, Powertrain: {powertrain_type})
            - Date: {formatted_date}
            - Location: {location}
            - Current Vehicle: {current_vehicle}
            - Time Frame: {time_frame}
            - **Lead Score: {lead_score_text}**
            - **Numeric Lead Score: {initial_numeric_score}**

            ---
            **Email Content Sent to Customer:**
            Subject: {generated_subject}
            To: {email}
            From: {EMAIL_ADDRESS}

            {generated_body}
            ---

            Please follow up accordingly.

            Best regards,
            AOE Motors System
            """.format(
                full_name=full_name,
                email=email,
                vehicle=vehicle,
                vehicle_type=vehicle_type,
                powertrain_type=powertrain_type,
                formatted_date=formatted_date,
                location=location,
                current_vehicle=current_vehicle,
                time_frame=time_frame,
                lead_score_text=lead_score_text,  # Use lead_score_text here
                initial_numeric_score=initial_numeric_score, # Pass numeric score
                generated_subject=generated_subject,
                EMAIL_ADDRESS=EMAIL_ADDRESS,
                generated_body=generated_body
            )
            msg_team = MIMEMultipart()
            msg_team["From"] = EMAIL_ADDRESS
            msg_team["To"] = TEAM_EMAIL
            msg_team["Subject"] = team_subject
            msg_team.attach(MIMEText(team_body, "plain")) # Plain text for internal clarity

            with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
                logging.debug(f"Attempting to connect to SMTP server for team email: {EMAIL_HOST}:{EMAIL_PORT}")
                server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                server.send_message(msg_team)
                logging.info(f"✅ Team notification email sent to {TEAM_EMAIL} (Subject: '{team_subject}').")
        else:
            logging.warning("TEAM_EMAIL not configured or email sending credentials missing. Skipping team notification.")

        # --- Save to Supabase ---
        try:
            booking_data = {
                "request_id": request_id,
                "full_name": full_name,
                "email": email,
                "vehicle": vehicle,
                "booking_date": date, 
                "location": location,
                "current_vehicle": current_vehicle,
                "time_frame": time_frame,
                "generated_subject": generated_subject,
                "generated_body": generated_body,
                "lead_score": lead_score_text,  # Save text score
                "numeric_lead_score": initial_numeric_score, # Save numeric score
                "booking_timestamp": datetime.now().isoformat(), 
                "action_status": 'New Lead', 
                "sales_notes": '',
                "phone": phone_raw,            # optional, for audit/visibility
                "phone_e164": phone_e164,      # optional, normalized for WA
            }
            response = supabase.from_(SUPABASE_TABLE_NAME).insert(booking_data).execute()
            if response.data:
                logging.info(f"✅ Booking data successfully saved to Supabase (request_id: {request_id}).")
            else:
                logging.error(f"❌ Failed to save booking data to Supabase for request_id {request_id}. Response: {response}")
        except Exception as e:
            logging.error(f"❌ Error saving booking data to Supabase for request_id {request_id}: {e}", exc_info=True)
        # ✅ Auto-kick WhatsApp only when we have a valid number
        if phone_e164:
            asyncio.create_task(_kick_wa_session(request_id))    

        return {"status": "success", "message": "Test drive request processed successfully and emails sent."}

    except Exception as e:
        logging.error(f"🚨 An unexpected error occurred during webhook processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")
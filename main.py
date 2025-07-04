import requests
from bs4 import BeautifulSoup
import time
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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
from playwright.sync_api import sync_playwright # NEW: Import Playwright

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

# Global variable to store cached vehicle data
# This will be populated once and refreshed periodically
cached_aoe_vehicles_data = {}
last_refresh_time = 0
REFRESH_INTERVAL_SECONDS = 3600 # Refresh every hour

# URL of the website to scrape vehicle data from
scrape_url = "https://aoe-motors.lovable.app/#vehicles" # UPDATED URL

# CORS Middleware for local development and Render deployment
origins = [
    "http://localhost",
    "http://localhost:8501", # Streamlit's default local port
    "http://localhost:3000",
    "https://aoe-motors-app-dashboard-g6uawbcwefimsjatxmnc4j.streamlit.app", # Your Streamlit Cloud app URL
    "https://aoe-agentic-demo.onrender.com", # Your Render backend URL
    "https://aoe-motors.lovable.app", # Your frontend/website where booking form is
    "*" # WARNING: Use '*' for development only. For production, restrict to known origins.
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Email Configuration (Moved from Streamlit app as per instructions) ---
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = os.getenv("EMAIL_PORT")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

ENABLE_EMAIL_SENDING = all([EMAIL_HOST, EMAIL_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD])

if not ENABLE_EMAIL_SENDING:
    logging.warning("Email sending is not fully configured. Please set EMAIL_HOST, EMAIL_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD environment variables.")

def send_email(to_email: str, subject: str, body: str):
    if not ENABLE_EMAIL_SENDING:
        logging.error(f"Email sending not configured. Cannot send email to {to_email}.")
        return False

    msg = MIMEMultipart()
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    try:
        logging.info(f"Attempting to send email to {to_email}...")
        server = smtplib.SMTP(EMAIL_HOST, int(EMAIL_PORT))
        server.starttls() # Secure the connection
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_ADDRESS, to_email, text)
        server.quit()
        logging.info(f"✅ Email successfully sent to {to_email}.")
        return True
    except Exception as e:
        logging.error(f"❌ Failed to send email to {to_email}: {e}", exc_info=True)
        return False

# --- OpenAI Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logging.error("OpenAI API Key environment variable not set.")
    raise ValueError("OpenAI API Key not found. Please set OPENAI_API_KEY in your .env file or Render environment.")
openai_client = OpenAI(api_key=OPENAI_API_KEY)


# Function to generate initial sales notes and lead score based on user input
def generate_initial_analysis(name: str, email: str, phone: str, vehicle: str, location: str, preferred_date: str, preferred_time: str, customer_query: str):
    prompt = f"""
    You are an AI assistant for AOE Motors. Your task is to analyze a new test drive booking request and generate:
    1. A concise initial sales note summarizing the lead's key information, needs, and potential next steps for the sales team.
    2. A lead score (Hot, Warm, Cold) based on the customer's query and details.

    Booking Details:
    - Name: {name}
    - Email: {email}
    - Phone: {phone}
    - Vehicle of Interest: {vehicle}
    - Location: {location}
    - Preferred Date: {preferred_date}
    - Preferred Time: {preferred_time}
    - Customer's Query/Message: {customer_query}

    Guidelines for Sales Note:
    - Summarize customer's interest and any specific questions.
    - Highlight the vehicle and location.
    - Suggest immediate next actions for the sales representative (e.g., confirm booking, prepare vehicle info, address specific query).
    - Keep it brief and actionable.

    Guidelines for Lead Score:
    - Hot: Clear intent to purchase or test drive, specific questions, good contact info.
    - Warm: General interest, some details provided, might need more nurturing.
    - Cold: Very vague query, incomplete info, seems like Browse.

    Example Output Format:
    SALES_NOTE: [Your generated sales note]
    LEAD_SCORE: [Hot/Warm/Cold]
    """

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o", # Or "gpt-3.5-turbo" for faster/cheaper
            messages=[
                {"role": "system", "content": "You are a helpful sales assistant."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300
        )
        content = response.choices[0].message.content.strip()
        
        sales_note_line = next((line for line in content.split('\n') if line.startswith("SALES_NOTE:")), "SALES_NOTE: No specific note generated.")
        lead_score_line = next((line for line in content.split('\n') if line.startswith("LEAD_SCORE:")), "LEAD_SCORE: Warm") # Default to Warm

        sales_note = sales_note_line.replace("SALES_NOTE:", "").strip()
        lead_score = lead_score_line.replace("LEAD_SCORE:", "").strip()
        
        # Ensure lead_score is one of the allowed values
        if lead_score not in ["Hot", "Warm", "Cold"]:
            lead_score = "Warm" # Fallback if AI hallucinates a different score

        return sales_note, lead_score

    except Exception as e:
        logging.error(f"Error generating initial analysis with OpenAI: {e}", exc_info=True)
        return f"Error generating notes: {e}", "Warm" # Default to Warm on error


# --- Web Scraping Function (UPDATED TO USE PLAYWRIGHT) ---
def fetch_aoe_vehicle_data_from_website():
    global cached_aoe_vehicles_data
    logging.info("Attempting to refresh cached vehicle data using Playwright...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True) # Run in headless mode (no UI)
            page = browser.new_page()
            page.goto(scrape_url, wait_until="networkidle") # Wait until network is idle

            # Wait for the specific vehicle cards to load. Adjust selector if needed.
            # This is crucial for dynamically loaded content.
            try:
                page.wait_for_selector(".vehicle-card", timeout=15000) # Wait up to 15 seconds for a vehicle card
                logging.info("Vehicle cards found, proceeding with scraping.")
            except Exception as e:
                logging.warning(f"Timeout waiting for .vehicle-card selector, page might not have fully loaded dynamic content: {e}")
                # Even if timeout, proceed to get content, maybe some static content is there

            html_content = page.content() # Get the full rendered HTML
            browser.close()

        # logging.info(f"Raw HTML content from {scrape_url}:\n{html_content[:2000]}...") # Debugging line - keep or remove

        soup = BeautifulSoup(html_content, 'html.parser')

        vehicles = {}
        vehicle_cards = soup.find_all('div', class_='vehicle-card')

        logging.info(f"Found {len(vehicle_cards)} vehicle cards on the page.")

        for card in vehicle_cards:
            name = card.find('h2', class_='vehicle-title').text.strip() if card.find('h2', class_='vehicle-title') else 'N/A'
            
            # Extract basic details like type and powertrain
            type_tag = card.find('p', class_='vehicle-type')
            vehicle_type = type_tag.text.replace('Type:', '').strip() if type_tag else 'N/A'

            powertrain_tag = card.find('p', class_='vehicle-powertrain')
            powertrain = powertrain_tag.text.replace('Powertrain:', '').strip() if powertrain_tag else 'N/A'
            
            features = []
            features_list = card.find('ul', class_='vehicle-features')
            if features_list:
                for feature_item in features_list.find_all('li'):
                    features.append(feature_item.text.strip())
            
            vehicles[name] = {
                "name": name,
                "type": vehicle_type,
                "powertrain": powertrain,
                "features": ", ".join(features) if features else "No features listed.",
                "image_url": card.find('img')['src'] if card.find('img') else 'N/A'
            }
        
        if vehicles:
            cached_aoe_vehicles_data = vehicles
            global last_refresh_time
            last_refresh_time = time.time()
            logging.info(f"✅ Successfully scraped {len(vehicles)} vehicles from {scrape_url}.")
        else:
            logging.warning(f"Successfully scraped 0 vehicles from {scrape_url}. No data to cache.")

    except Exception as e:
        logging.error(f"❌ Error fetching vehicle data from {scrape_url} using Playwright: {e}", exc_info=True)
        logging.warning("Failed to refresh vehicle data. Keeping existing cached data.")

# Route to get cached vehicle data
@app.get("/vehicles-data")
async def get_vehicles_data():
    global last_refresh_time
    # Refresh data if cache is empty or interval has passed
    if not cached_aoe_vehicles_data or (time.time() - last_refresh_time) > REFRESH_INTERVAL_SECONDS:
        fetch_aoe_vehicle_data_from_website()
    
    # If after refresh, data is still empty, attempt to re-scrape once more immediately
    # This handles cases where the initial scrape might have failed but could succeed on retry
    if not cached_aoe_vehicles_data:
        logging.warning("Cached vehicle data is still empty after initial refresh attempt. Retrying scrape...")
        fetch_aoe_vehicle_data_from_website() # Retry once

    if not cached_aoe_vehicles_data:
        raise HTTPException(status_code=503, detail="Vehicle data not available. Scraping failed.")
    
    return cached_aoe_vehicles_data

# Ensure data is fetched when the application starts
# This will happen when Render deploys the app
@app.on_event("startup")
async def startup_event():
    logging.info("Backend starting up. Initializing vehicle data scrape...")
    # Trigger initial data fetch immediately upon startup
    fetch_aoe_vehicle_data_from_website()


# Define the request body model for the webhook
class TestDriveRequest(BaseModel):
    name: str
    email: str
    phone: str
    vehicle: str
    location: str
    preferred_date: str
    preferred_time: str
    customer_query: str

# Webhook endpoint to receive test drive requests
@app.post("/webhook/testdrive")
async def receive_test_drive_request(request: TestDriveRequest):
    request_id = str(uuid.uuid4()) # Generate a unique request ID
    logging.info(f"Received new test drive request (request_id: {request_id}): {request.dict()}")

    try:
        # Generate initial sales notes and lead score
        initial_sales_note, lead_score = generate_initial_analysis(
            name=request.name,
            email=request.email,
            phone=request.phone,
            vehicle=request.vehicle,
            location=request.location,
            preferred_date=request.preferred_date,
            preferred_time=request.preferred_time,
            customer_query=request.customer_query
        )
        logging.info(f"Generated initial sales note for {request_id}: {initial_sales_note}")
        logging.info(f"Generated lead score for {request_id}: {lead_score}")

        # Send confirmation email to the customer
        customer_subject = "AOE Motors: Your Test Drive Request Confirmation"
        customer_body = f"""Dear {request.name},

Thank you for your interest in a test drive with AOE Motors!

We have received your request for a test drive of the:
- Vehicle: {request.vehicle}
- Location: {request.location}
- Preferred Date: {request.preferred_date}
- Preferred Time: {request.preferred_time}

A sales representative will contact you shortly to confirm the details and answer any specific questions you may have regarding your query: "{request.customer_query}".

We look forward to seeing you!

Best regards,
The AOE Motors Team
"""
        send_email(request.email, customer_subject, customer_body)

        # Send notification email to the sales team (or relevant personnel)
        sales_subject = f"NEW TEST DRIVE LEAD: {request.name} - {request.vehicle}"
        sales_body = f"""A new test drive request has been submitted:

Request ID: {request_id}
Name: {request.name}
Email: {request.email}
Phone: {request.phone}
Vehicle of Interest: {request.vehicle}
Location: {request.location}
Preferred Date: {request.preferred_date}
Preferred Time: {request.preferred_time}
Customer Query: {request.customer_query}

Initial Sales Note: {initial_sales_note}
Lead Score: {lead_score}

Please follow up with this lead promptly.
"""
        # This email would go to a sales team's inbox, for example
        # For demo, you might send it to a test email address
        send_email(os.getenv("SALES_TEAM_EMAIL", EMAIL_ADDRESS), sales_subject, sales_body) # Defaults to sender if not set

        # Save booking data to Supabase
        try:
            booking_data = {
                "request_id": request_id,
                "name": request.name,
                "email": request.email,
                "phone": request.phone,
                "vehicle": request.vehicle,
                "location": request.location,
                "preferred_date": request.preferred_date,
                "preferred_time": request.preferred_time,
                "customer_query": request.customer_query,
                "initial_sales_note": initial_sales_note,
                "generated_subject": customer_subject, # Storing the customer email subject for reference
                "generated_body": customer_body, # Storing the customer email body for reference
                "lead_score": lead_score,
                "booking_timestamp": datetime.now().isoformat(), # ISO format for Supabase datetime
                "action_status": 'New Lead', # Default
                "sales_notes": '' # Default empty
            }
            response = supabase.from_(SUPABASE_TABLE_NAME).insert(booking_data).execute()
            if response.data:
                logging.info(f"✅ Booking data successfully saved to Supabase (request_id: {request_id}).")
            else:
                logging.error(f"❌ Failed to save booking data to Supabase for request_id {request_id}. Response: {response}")
                # You might choose to raise an HTTPException here if DB save is critical
        except Exception as e:
            logging.error(f"❌ Error saving booking data to Supabase for request_id {request_id}: {e}", exc_info=True)
            # Decide if this should be a critical failure for the webhook or just logged
            # For now, it will return success if emails are sent, but log DB failure

        return {"status": "success", "message": "Test drive request processed successfully and emails sent."}

    except Exception as e:
        logging.error(f"🚨 An unexpected error occurred during webhook processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")
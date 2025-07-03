
# This is a placeholder. If the original file was not saved properly,
# we should regenerate it based on prior updates.
# For now, just indicating file regeneration point.
import os
import logging
import sys
from fastapi import FastAPI, Request, HTTPException
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from bs4 import BeautifulSoup
import openai
from supabase import create_client, Client
import uuid
# from dotenv import load_dotenv # Keep this commented out for Render, as it handles env vars directly

# Ensure logging is configured early and set to DEBUG level
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

# --- START ENVIRONMENT VARIABLE DEBUGGING ---
logging.debug("--- Starting Environment Variable Debugging ---")
logging.debug(f"Raw SUPABASE_URL from os.getenv: '{os.getenv('SUPABASE_URL')}'")
logging.debug(f"Raw SUPABASE_KEY from os.getenv: '{os.getenv('SUPABASE_KEY')}'")
logging.debug(f"Raw OPENAI_API_KEY from os.getenv: '{os.getenv('OPENAI_API_KEY')}'")
logging.debug(f"Raw EMAIL_HOST from os.getenv: '{os.getenv('EMAIL_HOST')}'")
logging.debug(f"Raw EMAIL_PORT from os.getenv: '{os.getenv('EMAIL_PORT')}'")
logging.debug(f"Raw EMAIL_ADDRESS from os.getenv: '{os.getenv('EMAIL_ADDRESS')}'")
logging.debug(f"Raw EMAIL_PASSWORD from os.getenv: '{os.getenv('EMAIL_PASSWORD')}'")
logging.debug(f"Raw TEAM_EMAIL from os.getenv: '{os.getenv('TEAM_EMAIL')}'")
logging.debug("--- End Environment Variable Debugging ---")

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logging.error("Supabase URL or Key environment variables are not set.")
    raise ValueError("Supabase credentials not found. Please set SUPABASE_URL and SUPABASE_KEY in your Render environment settings.")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logging.error("OPENAI_API_KEY environment variable is not set.")
    raise ValueError("OpenAI API key not found. Please set OPENAI_API_KEY in your Render environment settings.")
openai.api_key = OPENAI_API_KEY

EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587)) # Default to 587 if not set
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
TEAM_EMAIL = os.getenv("TEAM_EMAIL")

# Note: Added a check for email variables too, though not raising ValueError here.
# If these are missing, email sending will fail later.
if not all([EMAIL_HOST, EMAIL_ADDRESS, EMAIL_PASSWORD, TEAM_EMAIL]):
    logging.warning("One or more email environment variables (EMAIL_HOST, EMAIL_ADDRESS, EMAIL_PASSWORD, TEAM_EMAIL) are not set. Email functionality may be affected.")


app = FastAPI()

# Functions (reconstructed based on previous context and typical patterns)
async def get_vehicle_data(url: str):
    """Fetches vehicle data by scraping the given URL."""
    try:
        response = requests.get(url)
        response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
        soup = BeautifulSoup(response.content, 'html.parser')
        vehicles = []
        # These selectors are placeholders. Adjust based on the actual HTML structure
        # of https://aoe-motors.lovable.app/#vehicles
        vehicle_cards = soup.find_all('div', class_='vehicle-item') # Common class names might be 'product-card', 'car-listing' etc.
        for card in vehicle_cards:
            name_tag = card.find('h3', class_='vehicle-title') # e.g., 'h2', 'span'
            price_tag = card.find('span', class_='vehicle-price') # e.g., 'p', 'div'
            if name_tag and price_tag:
                vehicles.append({
                    'name': name_tag.get_text(strip=True),
                    'price': price_tag.get_text(strip=True)
                })
        logging.debug(f"Fetched vehicle data: {vehicles}")
        return vehicles
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching vehicle data from {url}: {e}")
        return []
    except Exception as e:
        logging.error(f"An unexpected error occurred during vehicle data scraping: {e}")
        return []

async def send_email(subject: str, body: str, to_email: str):
    """Sends an email using SMTP."""
    if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD]):
        logging.error("Email sending skipped: Missing SMTP configuration.")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html')) # Assuming HTML body from OpenAI

        # Use SMTP_SSL for port 465, or SMTP for other ports (e.g., 587 with starttls)
        # For simplicity, using SMTP_SSL as 465 is common for SSL
        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)
        logging.info(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        logging.error(f"Failed to send email to {to_email}: {e}")
        return False

async def idempotency_check(booking_id: str):
    """Checks if a booking ID already exists in Supabase."""
    try:
        response = supabase.from_("test_drive_bookings").select("id").eq("booking_id", booking_id).execute()
        if response.data:
            logging.info(f"Idempotency check: Booking ID {booking_id} already exists.")
            return True # Booking already exists
        logging.debug(f"Idempotency check: Booking ID {booking_id} does not exist.")
        return False
    except Exception as e:
        logging.error(f"Supabase idempotency check failed for ID {booking_id}: {e}")
        return False

async def insert_into_supabase(data: dict):
    """Inserts data into the 'test_drive_bookings' table in Supabase."""
    try:
        response = supabase.from_("test_drive_bookings").insert(data).execute()
        if response.data:
            logging.info(f"Successfully inserted data into Supabase: {response.data}")
            return True
        else:
            logging.error(f"Supabase insert failed: No data returned. Status: {response.status_code}")
            return False
    except Exception as e:
        logging.error(f"Error inserting into Supabase: {e}")
        return False

@app.post("/webhook/testdrive")
async def handle_testdrive_webhook(request: Request):
    """Handles incoming webhook requests for test drive bookings."""
    try:
        payload = await request.json()
        logging.info(f"Received webhook payload: {payload}")

        full_name = payload.get("full_name")
        email = payload.get("email")
        phone_number = payload.get("phone_number")
        preferred_model = payload.get("preferred_model")
        preferred_date = payload.get("preferred_date")
        preferred_time = payload.get("preferred_time")
        location = payload.get("location")
        booking_id = str(uuid.uuid4()) # Generate a unique booking ID for this request

        if not all([full_name, email, preferred_model, preferred_date, preferred_time, location]):
            logging.warning("Missing required fields in webhook payload.")
            raise HTTPException(status_code=400, detail="Missing required fields for test drive booking.")

        # Perform idempotency check to avoid duplicate entries
        if await idempotency_check(booking_id):
            logging.info(f"Duplicate booking detected for ID: {booking_id}. Responding with success.")
            return {"status": "success", "message": "Booking already exists."}

        # Scrape vehicle data for context to provide to OpenAI
        aoe_motors_url = "https://aoe-motors.lovable.app/#vehicles"
        vehicle_data = await get_vehicle_data(aoe_motors_url)
        selected_vehicle_info = next((v for v in vehicle_data if v.get('name') == preferred_model), None)
        vehicle_details_for_prompt = ""
        if selected_vehicle_info:
            vehicle_details_for_prompt = f" (Details: Name: {selected_vehicle_info['name']}, Price: {selected_vehicle_info['price']})"
        
        # Generate email content using OpenAI
        prompt_template = f"""
        Generate a professional and enthusiastic email for a test drive confirmation.
        The customer's name is {full_name}.
        They have requested a test drive for the {preferred_model}{vehicle_details_for_prompt}.
        The preferred date is {preferred_date} and time is {preferred_time}, in {location}.
        Confirm the test drive and provide next steps.
        Also include a catchy subject line.
        Suggest they bring a valid driver's license.
        Mention that our team will be in touch shortly to finalize details.
        Use a friendly, luxurious tone suitable for a premium electric vehicle brand like AOE Motors.
        Include a link to our website for more models: https://aoe-motors.lovable.app/#vehicles
        Include a link to our contact page: https://aoe-motors.lovable.app/#contact
        """
        
        # Ensure OpenAI API key is set before calling
        if not openai.api_key:
            logging.error("OpenAI API key is not initialized.")
            raise HTTPException(status_code=500, detail="OpenAI API key not configured.")

        response = openai.chat.completions.create(
            model="gpt-4", # You can also use "gpt-3.5-turbo" for potentially lower cost
            messages=[
                {"role": "system", "content": "You are a helpful assistant for AOE Motors, a luxury electric vehicle brand. You craft engaging and informative emails."},
                {"role": "user", "content": prompt_template}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        generated_email_content = response.choices[0].message.content
        
        # Attempt to extract subject line from generated content
        subject_line = "AOE Motors Test Drive Confirmation" # Default subject
        body_content = generated_email_content

        # Simple heuristic to find subject: if content starts with "Subject: "
        if '\n' in generated_email_content:
            first_newline_index = generated_email_content.find('\n')
            subject_candidate = generated_email_content[:first_newline_index].strip()
            if subject_candidate.lower().startswith("subject:"):
                subject_line = subject_candidate[len("subject:"):].strip()
                body_content = generated_email_content[first_newline_index:].strip()
            else:
                body_content = generated_email_content # If no clear subject line, use full content as body

        logging.debug(f"Generated Email Subject: {subject_line}")
        logging.debug(f"Generated Email Body (first 100 chars): {body_content[:100]}...")
        
        # Prepare data for Supabase insertion
        booking_data = {
            "booking_id": booking_id,
            "full_name": full_name,
            "email": email,
            "phone_number": phone_number,
            "preferred_model": preferred_model,
            "preferred_date": preferred_date,
            "preferred_time": preferred_time,
            "location": location,
            "email_subject": subject_line,
            "email_body": body_content,
            "timestamp": datetime.now().isoformat()
        }

        # Insert into Supabase
        insertion_success = await insert_into_supabase(booking_data)
        if not insertion_success:
            logging.error("Failed to insert booking data into Supabase.")
            raise HTTPException(status_code=500, detail="Failed to record test drive booking.")
        
        # Send confirmation email to customer
        customer_email_success = await send_email(subject_line, body_content, email)
        if not customer_email_success:
            logging.error(f"Failed to send confirmation email to customer: {email}. Booking was recorded in DB.")
            # Do not raise HTTPException here if DB insertion was successful, as email failure might be retriable or secondary

        # Send notification to internal team
        team_notification_subject = f"New Test Drive Request: {full_name} for {preferred_model}"
        team_notification_body = f"""
        A new test drive has been requested:
        Customer: {full_name} ({email})
        Phone: {phone_number if phone_number else 'N/A'}
        Model: {preferred_model}
        Date: {preferred_date}
        Time: {preferred_time}
        Location: {location}
        Booking ID: {booking_id}
        """
        await send_email(team_notification_subject, team_notification_body, TEAM_EMAIL)

        return {"status": "success", "message": "Test drive booked and confirmation email sent."}

    except HTTPException as e:
        logging.error(f"HTTP Exception: {e.detail}")
        raise e
    except Exception as e:
        logging.exception("An unexpected error occurred during test drive webhook processing.")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.get("/")
async def read_root():
    """Root endpoint for the API."""
    return {"message": "Welcome to AOE Motors Test Drive API. Send a POST request to /webhook/testdrive to book a test drive."}
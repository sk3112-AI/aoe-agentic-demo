import requests
from bs4 import BeautifulSoup
import time
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel # NEW: Import BaseModel for request body validation
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from datetime import datetime
import logging
import sys
from openai import OpenAI
import uuid # Import uuid for generating request IDs
from supabase import create_client, Client # Import Supabase client

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

# Global variable to store cached vehicle data and last refresh time
cached_aoe_vehicles_data = {}
LAST_DATA_REFRESH_TIME = 0 # Unix timestamp
REFRESH_INTERVAL_SECONDS = 3600 # Refresh every hour (3600 seconds)

# Email configuration
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 465)) # Default to 465 for SSL

# Team Email for notifications
TEAM_EMAIL = os.getenv("TEAM_EMAIL")

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


def fetch_aoe_vehicle_data_from_website():
    """
    Scrapes vehicle data from the AOE Motors website.
    Returns a dictionary of vehicle data, or None on failure.
    """
    url = "https://www.aoemotors.com/vehicles"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status() # Raise an exception for HTTP errors
        soup = BeautifulSoup(response.text, 'html.parser')

        vehicles = {}
        vehicle_cards = soup.find_all('div', class_='vehicle-card') # Adjust class based on actual HTML

        for card in vehicle_cards:
            name_tag = card.find('h2', class_='vehicle-name')
            type_tag = card.find('p', class_='vehicle-type')
            powertrain_tag = card.find('p', class_='vehicle-powertrain')
            features_tag = card.find('ul', class_='vehicle-features') # Assuming features are in a ul

            name = name_tag.text.strip() if name_tag else "Unknown Vehicle"
            vehicle_type = type_tag.text.replace("Type:", "").strip() if type_tag else "Unknown Type"
            powertrain = powertrain_tag.text.replace("Powertrain:", "").strip() if powertrain_tag else "Unknown Powertrain"
            
            features = []
            if features_tag:
                for li in features_tag.find_all('li'):
                    features.append(li.text.strip())
            
            vehicles[name] = {
                "type": vehicle_type,
                "powertrain": powertrain,
                "features": ", ".join(features) if features else "No specific features listed."
            }
        logging.info(f"Successfully scraped {len(vehicles)} vehicles from {url}.")
        return vehicles

    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching vehicle data from {url}: {e}", exc_info=True)
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during scraping: {e}", exc_info=True)
        return None

def scrape_aoe_vehicles_data():
    """
    Refreshes the global cached_aoe_vehicles_data if the refresh interval has passed.
    """
    global cached_aoe_vehicles_data, LAST_DATA_REFRESH_TIME
    if time.time() - LAST_DATA_REFRESH_TIME > REFRESH_INTERVAL_SECONDS:
        logging.info("Attempting to refresh cached vehicle data...")
        new_data = fetch_aoe_vehicle_data_from_website()
        if new_data:
            cached_aoe_vehicles_data = new_data
            LAST_DATA_REFRESH_TIME = time.time()
            logging.info("Cached vehicle data successfully refreshed.")
        else:
            logging.warning("Failed to refresh vehicle data. Keeping existing cached data.")
    else:
        logging.info("Skipping vehicle data refresh. Interval not yet passed.")

# Initial data load when the application starts
scrape_aoe_vehicles_data()


def get_vehicle_resources(vehicle_name: str):
    """
    Returns mock resource links (YouTube, PDF) for a given vehicle.
    In a real application, this would fetch from a database or API.
    """
    resources = {
        "Apex": {
            "youtube_link": "https://www.youtube.com/watch?v=aoe_apex_overview",
            "pdf_link": "https://www.aoemotors.com/docs/apex_guide.pdf"
        },
        "Volt": {
            "youtube_link": "https://www.youtube.com/watch?v=aoe_volt_review",
            "pdf_link": "https://www.aoemotors.com/docs/volt_specs.pdf"
        },
        "Aero": {
            "youtube_link": "https://www.youtube.com/watch?v=aoe_aero_features",
            "pdf_link": "https://www.aoemotors.com/docs/aero_brochure.pdf"
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

# --- DEBUG LOGGING ENDPOINT ---
@app.get("/debug-logs")
async def get_debug_logs():
    """Endpoint to retrieve recent debug logs."""
    # This is a placeholder. In a real app, you'd fetch from a log file or streaming service.
    # For now, it just shows the recent messages that went to stdout/stderr.
    logging.info("Debug logs requested.")
    # This won't capture all past logs, only what's still in the buffer
    return {"message": "Debug logging is active. Check server console for full logs."}
# --- END DEBUG LOGGING ---


@app.get("/")
async def read_root():
    """Root endpoint for the API."""
    return {"message": "Welcome to AOE Motors Test Drive API. Send a POST request to /webhook/testdrive to book a test drive."}

# EXISTING ENDPOINT FOR VEHICLE DATA
@app.get("/vehicles-data")
async def get_vehicles_data():
    """
    Endpoint to retrieve cached (and periodically refreshed) AOE Motors vehicle data.
    """
    try:
        # Ensure the scraping function is called to refresh data if needed
        # This function updates the global cached_aoe_vehicles_data
        scrape_aoe_vehicles_data()
        return cached_aoe_vehicles_data
    except Exception as e:
        logging.error(f"❌ Error retrieving vehicle data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve vehicle data.")

# NEW ENDPOINT 1: Update Booking Status and Sales Notes
class UpdateBookingRequest(BaseModel):
    request_id: str
    action_status: str
    sales_notes: str = None # Optional, can be empty

@app.post("/update-booking")
async def update_booking(request_body: UpdateBookingRequest):
    """
    Endpoint to update a booking's action_status and sales_notes in Supabase.
    """
    try:
        update_data = {
            "action_status": request_body.action_status,
            "sales_notes": request_body.sales_notes
        }
        response = supabase.from_(SUPABASE_TABLE_NAME).update(update_data).eq('request_id', request_body.request_id).execute()

        if response.data:
            logging.info(f"✅ Booking {request_body.request_id} updated successfully.")
            return {"status": "success", "message": "Booking updated successfully."}
        else:
            logging.error(f"❌ Failed to update booking {request_id}. Response: {response}")
            raise HTTPException(status_code=500, detail="Failed to update booking.")
    except Exception as e:
        logging.error(f"🚨 Error updating booking {request_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

# NEW ENDPOINT 2: Draft and Send Follow-up Email
class DraftAndSendEmailRequest(BaseModel):
    customer_name: str
    customer_email: str
    vehicle_name: str
    sales_notes: str
    vehicle_details: dict # Pass the relevant vehicle details from frontend

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
        - Acknowledge their test drive or recent interaction.
        - **Crucially, directly address the customer's stated issues from the sales notes.** For each issue mentioned, explain how specific features of the AOE {request_body.vehicle_name} (from the provided list) directly resolve or alleviate that concern.
            - If "high EV cost" is mentioned: Focus on long-term savings, reduced fuel costs, potential tax credits, Vehicle-to-Grid (V2G) if applicable (Volt).
            - If "charging anxiety" is mentioned: Highlight ultra-fast charging, solar integration (Volt), extensive charging network, range.
            - If other issues are mentioned: Adapt relevant features.
        - If no specific issues are mentioned, write a general follow-up highlighting key benefits.
        - End with a call to action to schedule another call or visit to discuss further.
        - Maintain a professional, empathetic, and persuasive tone.
        - **Output only the email content (Subject and Body), in plain text format.** Do NOT use HTML.
        - **Separate Subject and Body with "Subject: " at the beginning of the subject line.**
        """

        # Generate email content using OpenAI
        logging.info(f"Generating follow-up email for {request_body.customer_email} with OpenAI...")
        completion = openai_client.chat.completions.create(
            model="gpt-3.5-turbo", # You can use "gpt-4o" for better quality if available
            messages=[
                {"role": "system", "content": "You are a helpful and persuasive sales assistant for AOE Motors."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=600
        )
        draft = completion.choices[0].message.content.strip()

        subject_line = "Follow-up from AOE Motors"
        body_content = draft
        if "Subject:" in draft:
            parts = draft.split("Subject:", 1)
            subject_line = parts[1].split("\n", 1)[0].strip()
            body_content = parts[1].split("\n", 1)[1].strip()
        
        logging.info(f"Generated Follow-up Subject: {subject_line}")

        # Send the email
        if EMAIL_ADDRESS and EMAIL_PASSWORD and EMAIL_HOST and EMAIL_PORT:
            msg = MIMEMultipart()
            msg["From"] = EMAIL_ADDRESS
            msg["To"] = request_body.customer_email
            msg["Subject"] = subject_line
            msg.attach(MIMEText(body_content, "plain"))

            with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
                server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                server.send_message(msg)
            logging.info(f"✅ Follow-up email sent to {request_body.customer_email}")
            return {"status": "success", "message": "Email drafted and sent successfully!", "subject": subject_line, "body": body_content}
        else:
            logging.warning("Email sending credentials not fully configured. Email not sent.")
            return {"status": "warning", "message": "Email drafted, but not sent (credentials missing).", "subject": subject_line, "body": body_content}

    except Exception as e:
        logging.error(f"🚨 Error drafting or sending email for {request_body.customer_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error during email process: {e}")


@app.post("/webhook/testdrive")
async def testdrive_webhook(request: Request):
    logging.info("Webhook /testdrive received a request.")
    data = await request.json()

    logging.debug(f"Received data: {data}")

    # Extract request_id for idempotency
    request_id = data.get("requestId")
    if not request_id:
        # Generate a UUID if requestId is not provided by the client, for idempotency
        request_id = str(uuid.uuid4())
        logging.warning(f"No 'requestId' provided in the payload. Generating new: {request_id}")

    # --- Idempotency Check (before processing or sending emails) ---
    try:
        response = supabase.from_(SUPABASE_TABLE_NAME).select("id").eq("request_id", request_id).execute()
        if response.data:
            logging.info(f"Duplicate request (requestId: {request_id}) received. Already processed. Ignoring to prevent continuous emails.")
            return {"status": "success", "message": "Test drive request already processed."}
    except Exception as e:
        logging.error(f"Error during Supabase idempotency check for requestId {request_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error during idempotency check: {e}")
    # --- End Idempotency Check ---

    full_name = data.get("fullName", "")
    email = data.get("email", "")
    vehicle = data.get("vehicle", "")
    date = data.get("date", "")
    location = data.get("location", "")
    current_vehicle = data.get("currentVehicle", "no vehicle").lower().strip()
    time_frame = data.get("timeFrame", "exploring").lower().strip()

    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%B %d, %Y")
    except ValueError as e:
        logging.error(f"Error parsing date '{date}': {e}", exc_info=True)
        return {"status": "error", "message": "Invalid date format"}

    # --- Dynamic Vehicle Data Retrieval ---
    global cached_aoe_vehicles_data, LAST_DATA_REFRESH_TIME

    if time.time() - LAST_DATA_REFRESH_TIME > REFRESH_INTERVAL_SECONDS:
        logging.info("Refreshing cached vehicle data...")
        new_data = fetch_aoe_vehicle_data_from_website()
        if new_data: 
            cached_aoe_vehicles_data = new_data
            LAST_DATA_REFRESH_TIME = time.time() 
            logging.info("Cached vehicle data refreshed.")
        else:
            logging.warning("Failed to refresh vehicle data. Continuing with old cached data.")
    
    vehicle_info = cached_aoe_vehicles_data.get(vehicle, {
        "type": "vehicle", 
        "powertrain": "advanced performance", 
        "features": "cutting-edge technology and futuristic design." 
    })

    vehicle_type = vehicle_info["type"]
    powertrain_type = vehicle_info["powertrain"]
    chosen_aoe_features = vehicle_info["features"]

    # --- Get Dynamic Resource Links ---
    resources = get_vehicle_resources(vehicle)
    youtube_link = resources["youtube_link"]
    pdf_link = resources["pdf_link"]


    # Determine tone based on time frame for email body and subject
    tone_instruction_body = "The tone should be enthusiastic and persuasive, highlighting immediate benefits."
    tone_instruction_subject = "Use a highly persuasive and exciting tone."
    if time_frame == "0-3-months":
        tone_instruction_body = "The tone should be highly persuasive, emphasizing immediate benefits and exclusive offers for their upcoming purchase decision, *without* implying the test drive itself is the only window for these benefits."
        tone_instruction_subject = "Use a highly persuasive and exciting tone, suggesting urgency related to purchasing."
    elif time_frame == "3-6-months":
        tone_instruction_body = "The tone should be informative and encouraging, focusing on future benefits and guiding them through the next steps in their consideration process."
        tone_instruction_subject = "Use an informative and encouraging tone, highlighting key features."
    elif time_frame == "6-12-months":
        tone_instruction_body = "The tone should be informative and helpful, inviting further exploration and offering detailed insights for their long-term decision-making."
        tone_instruction_subject = "Use an informative and helpful tone, suggesting further research."
    elif time_frame == "exploring":
        tone_instruction_body = "The tone should be welcoming and inviting, providing general information without pressure and encouraging casual exploration and discovery."
        tone_instruction_subject = "Use a welcoming and inviting tone, focusing on discovery."


    generated_subject = ""
    generated_body = ""
    lead_score = "Unknown" # Default value

    try:
        if not OPENAI_API_KEY or not openai_client:
            raise ValueError("OpenAI client not initialized. Check API key.")

        # --- 1. Dynamic Subject Line Generation ---
        logging.info(f"Attempting to generate subject line for {email} using OpenAI...")
        subject_prompt = f"""
        Generate a concise and engaging email subject line for a test drive confirmation.

        **Context:**
        - Customer: {full_name}
        - Vehicle: {vehicle} (Type: {vehicle_type}, Powertrain: {powertrain_type})
        - Test Drive Date: {formatted_date}
        - Location: {location}
        - Customer's Current Vehicle: {current_vehicle}
        - Purchase Time Frame: {time_frame}

        **Instructions:**
        - {tone_instruction_subject}
        - Keep it brief (under 15 words).
        - Do NOT include "Subject:" or any salutation/closing in the output.
        - Example: "Your Apex Test Drive is Confirmed!" or "Experience the Volt: Your Test Drive Awaits!"
        - **STRICTLY ensure factual accuracy about the vehicle type and powertrain.**
        - **Do NOT confuse 'Vehicle Type' with 'Powertrain Type'.** For {vehicle}, the vehicle type is {vehicle_type} and the powertrain is {powertrain_type}.
        """
        subject_completion = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant for AOE Motors, specializing in catchy email subjects. You must be factually accurate about vehicle details."},
                {"role": "user", "content": subject_prompt}
            ],
            temperature=0.7,
            max_tokens=50
        )
        generated_subject = subject_completion.choices[0].message.content.strip()
        logging.debug(f"Generated Subject: '{generated_subject}'")


        # --- 2. Generate Complete Email Body (UPDATED PROMPT with HTML enforcement and time frame fix) ---
        logging.info(f"Attempting to generate email body for {email} using OpenAI...")
        body_prompt = f"""
        You are an AI assistant for AOE Motors, crafting a personalized test drive confirmation email.

        **Goal:** Generate the complete body of a professional, engaging, and highly persuasive email. The email should be easy to read, visually appealing, concise, and relevant.

        **Customer Details:**
        - Full Name: {full_name}
        - Email: {email}
        - Vehicle of Interest: {vehicle}
        - Vehicle Type: {vehicle_type}
        - Vehicle Powertrain: {powertrain_type}
        - Test Drive Date: {formatted_date}
        - Test Drive Location: {location}
        - Customer's Current Vehicle: {current_vehicle} (if 'no vehicle', indicate they are exploring new options)
        - Purchase Time Frame: {time_frame} (refers to purchase intent/readiness, NOT test drive date)

        **AOE Vehicle Features (for {vehicle}):**
        - {chosen_aoe_features}

        **Resource Links (for {vehicle}):**
        - YouTube Link: {youtube_link}
        - PDF Guide Link: {pdf_link}

        **Instructions for Email Content:**
        1.  Start with a warm greeting to {full_name}.
        2.  **Crucial:** **ABSOLUTELY DO NOT include the subject line or any "Subject:" prefix in the email body.**
        3.  **STRICT Formatting Output Rules (MUST use HTML <p> tags):**
            * **The entire email body MUST be composed of distinct HTML paragraph tags (`<p>...</p>`).**
            * **Each logical section/paragraph MUST be entirely enclosed within its own `<p>` and `</p>` tags.**
            * **Each paragraph (`<p>...</p>`) should be concise (typically 2-4 sentences maximum).**
            * **Aim for a total of 5-7 distinct HTML paragraphs.**
            * **DO NOT use `\\n\\n` for spacing; the `<p>` tags provide the necessary visual separation.**
            * **DO NOT include any section dividers (like '---').**
            * **Ensure there is no extra blank space before the first `<p>` tag or after the last `</p>` tag.**

        **Content Structure & Logic (Each point should be a distinct HTML paragraph):**

        * **Paragraph 1 (Greeting & Test Drive Confirmation):**
            * Confirm the test drive details (vehicle, date, location) immediately, emphasizing excitement.
            * Example: "<p>Dear {full_name},</p><p>We are thrilled to confirm your upcoming test drive of the {vehicle} on {formatted_date} in {location}. Get ready for an exhilarating experience!</p>"

        * **Paragraph 2 (Vehicle Features & Persuasive Comparison):**
            * From the provided {chosen_aoe_features}, **select and highlight only 2-3 MOST EXCITING and UNIQUE features**. Integrate these naturally into the paragraph, explicitly mentioning its {vehicle_type} and {powertrain_type}.
            * Focus on the *experience* and *benefits* those 2-3 features provide. Do NOT simply list features or include more than 3.
            * **Crucial Comparison Logic:**
                * If `current_vehicle` is provided (and not 'no vehicle' or 'exploring'), subtly position the {vehicle} as a significant, transformative upgrade. Example: "As a {current_vehicle} owner, prepare to experience the next level of automotive innovation with the AOE {vehicle} {vehicle_type}, a remarkable {powertrain_type} vehicle that offers..." **Avoid any blunt or negative comparisons.**
                * If `current_vehicle` is 'no vehicle' or 'exploring', frame it as an exciting new kind of driving experience, a leap into advanced {powertrain_type} {vehicle_type} technology, or an opportunity to discover what makes AOE Motors unique.

        * **Paragraph 3 (Personalized Support for Your Journey - CRITICAL IMPLICIT FIX):**
            * This paragraph will *exclusively* address the '{time_frame}' for *purchase intent*.
            * **CRITICAL: This paragraph MUST NOT explicitly mention '{time_frame}' or any specific timeframe (e.g., '0-3 months', '3-6 months', '6-12 months', 'exploring'). Convey the time frame *implicitly* through the tone and focus of the support offered, using phrasing that aligns with their readiness.**
            * If `time_frame` is '0-3-months': Emphasize AOE Motors' readiness to support their swift decision, hinting at tailored support and exclusive opportunities for those ready to embrace the future soon.
                * *Example Implicit Phrasing:* "We understand you're ready to make a swift decision, and our team is poised to offer tailored support and exclusive opportunities as you approach ownership."
            * If `time_frame` is '3-6-months' or '6-12-months': Focus on offering continued guidance and resources throughout their decision-making journey, highlighting that you're ready to assist them when they're closer to a purchase decision, providing resources for further exploration.
                * *Example Implicit Phrasing:* "As you carefully consider your options over the coming months, we are committed to providing comprehensive support and insights to help you make an fresh choice."
            * If `time_frame` is 'exploring': Maintain a welcoming, low-pressure tone, focusing on discovery and making the experience informative and enjoyable for their future consideration, without implying urgency.
                * *Example Implicit Phrasing:* "We invite you to take your time exploring all the innovative features of the {vehicle} and discover how AOE Motors can fit your lifestyle, without any pressure."

        * **Paragraph 4 (Valuable Resources):**
            * Provide a sentence encouraging them to learn more.
            * Include two distinct hyperlinks: one for the `YouTube Link` (e.g., "Watch the AOE {vehicle} Overview Video") and one for the `PDF Guide Link` (e.g., "Download AOE {vehicle} Guide (PDF)").
            * Example: "<p>To learn even more about the {vehicle}, we invite you to watch our detailed video: <a href=\"{youtube_link}\">Watch the AOE {vehicle} Overview Video</a> and download the comprehensive guide: <a href=\"{pdf_link}\">Download AOE {vehicle} Guide (PDF)</a>.</p>"

        * **Paragraph 5 (Call to Action & Closing):**
            * Conclude with a clear and helpful call to action for any questions.
            * Express eagerness for their visit.
            * End with "Warm regards, Team AOE Motors" **within the same final paragraph's `<p>` tags.**
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
        lead_score = "Cold" # Default to Cold

        if time_frame == "0-3-months":
            lead_score = "Hot"
        elif time_frame == "3-6-months": # Interpreting "near to hot" as Warm
            lead_score = "Warm"
        elif time_frame == "6-12-months":
            lead_score = "Warm"
        elif time_frame == "exploring":
            lead_score = "Cold"
        logging.info(f"Rule-based Lead Score for {email}: '{lead_score}'")


        # --- Email Sending to Customer ---
        if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD]):
            raise ValueError("One or more email configuration environment variables are missing or empty.")

        msg_customer = MIMEMultipart()
        msg_customer["From"] = EMAIL_ADDRESS
        msg_customer["To"] = email
        msg_customer["Subject"] = generated_subject
        msg_customer.attach(MIMEText(generated_body, "html")) # Explicitly using 'html' to interpret <p> tags

        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
            logging.debug(f"Attempting to connect to SMTP server for customer email: {EMAIL_HOST}:{EMAIL_PORT}")
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg_customer)
            logging.info(f"✅ Customer email successfully sent to {email} (Subject: '{generated_subject}', Score: '{lead_score}').")

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
            - **Lead Score: {lead_score}**

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
                lead_score=lead_score,
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
                "booking_date": date, # Store as YYYY-MM-DD
                "location": location,
                "current_vehicle": current_vehicle,
                "time_frame": time_frame,
                "generated_subject": generated_subject,
                "generated_body": generated_body,
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
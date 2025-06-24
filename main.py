import requests
from bs4 import BeautifulSoup
import time
import json # In case we want to save/load cached data to a file for persistence across restarts
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from datetime import datetime
import logging
import sys
from openai import OpenAI
import sqlite3

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI()

# Database file path
DATABASE_FILE = "test_drives.db"

# Global variable to store cached vehicle data and last refresh time
cached_aoe_vehicles_data = {}
LAST_DATA_REFRESH_TIME = 0
REFRESH_INTERVAL_SECONDS = 4 * 3600 # Refresh every 4 hours (adjust as needed, e.g., 24*3600 for daily)

# DUMMY RESOURCE LINKS (for demonstration purposes)
# In a real application, these would likely come from a CMS or a proper database
DUMMY_VEHICLE_RESOURCES = {
    "AOE Apex": {
        "youtube_link": "https://www.youtube.com/watch?v=AOE_Apex_TestDrive_Dummy",
        "pdf_link": "https://www.aoemotors.com/guides/AOE_Apex_Guide_Dummy.pdf"
    },
    "AOE Thunder": {
        "youtube_link": "https://www.youtube.com/watch?v=AOE_Thunder_TestDrive_Dummy",
        "pdf_link": "https://www.aoemotors.com/guides/AOE_Thunder_Guide_Dummy.pdf"
    },
    "AOE Volt": {
        "youtube_link": "https://www.youtube.com/watch?v=AOE_Volt_TestDrive_Dummy",
        "pdf_link": "https://www.aoemotors.com/guides/AOE_Volt_Guide_Dummy.pdf"
    }
}

def get_vehicle_resources(vehicle_name: str):
    """
    Retrieves dummy resource links for a given vehicle.
    """
    return DUMMY_VEHICLE_RESOURCES.get(vehicle_name, {
        "youtube_link": "https://www.aoemotors.com/general-video-dummy",
        "pdf_link": "https://www.aoemotors.com/general-guide-dummy.pdf"
    })

# Function to initialize the database
def init_db():
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT,
                vehicle TEXT,
                booking_date TEXT,
                location TEXT,
                current_vehicle TEXT,
                time_frame TEXT,
                generated_subject TEXT,
                generated_body TEXT,
                lead_score TEXT,
                booking_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
        logging.info(f"Database '{DATABASE_FILE}' initialized successfully.")
    except Exception as e:
        logging.error(f"Failed to initialize database: {e}", exc_info=True)

def fetch_aoe_vehicle_data_from_website():
    """
    Fetches vehicle data by scraping the AOE Motors website.
    This implementation assumes a specific HTML structure.
    If the website's structure changes, this function will need to be updated.
    """
    url = "https://aoe-motors.lovable.app/#vehicles"
    logging.info(f"Attempting to fetch vehicle data from {url}...")
    try:
        response = requests.get(url, timeout=15) # Increased timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        soup = BeautifulSoup(response.text, 'html.parser')

        vehicles_data = {}
        
        main_content = soup.find('main') or soup # Fallback to whole soup if no main tag
        
        vehicle_name_tags = main_content.find_all(['h2', 'h3', 'h4']) # Look for common heading tags

        for tag in vehicle_name_tags:
            name = tag.get_text(strip=True)
            # Basic filtering for known AOE vehicles
            if "AOE" in name and ("Apex" in name or "Thunder" in name or "Volt" in name):
                features = "cutting-edge technology and futuristic design." # Default
                vehicle_type = "Vehicle" # Default
                powertrain = "Advanced" # Default

                next_p = tag.find_next_sibling('p')
                if next_p and len(next_p.get_text(strip=True)) > 20: # Heuristic: if it looks like a description
                    features = next_p.get_text(strip=True)
                
                # Manual override/fallback based on common AOE assumptions for accuracy
                if "Apex" in name:
                    vehicle_type = "Sedan"
                    powertrain = "Gasoline" # Corrected based on user feedback
                    if "powerful performance" not in features: # Updated features for Gasoline
                         features = "sleek design, powerful performance, and advanced safety features."
                elif "Thunder" in name:
                    vehicle_type = "SUV"
                    powertrain = "Gasoline"
                    if "bold design" not in features:
                         features = "bold design, advanced all-wheel drive system, and robust capability."
                elif "Volt" in name:
                    vehicle_type = "Compact EV"
                    powertrain = "EV"
                    if "instant torque" not in features:
                         features = "instant torque, zero-emission performance, and intelligent connectivity features."

                vehicles_data[name] = {
                    "type": vehicle_type,
                    "powertrain": powertrain,
                    "features": features
                }
        
        if not vehicles_data:
            logging.warning("No specific AOE vehicle data found by scraping. Using hardcoded defaults as fallback.")
            # Fallback to a hardcoded dictionary if scraping fails or returns empty
            # This is CRITICAL to prevent a complete breakdown if scraping fails
            vehicles_data = {
                "AOE Apex": {"type": "Sedan", "powertrain": "Gasoline", "features": "sleek design, powerful performance, and advanced safety features."}, # Corrected fallback
                "AOE Thunder": {"type": "SUV", "powertrain": "Gasoline", "features": "bold design, advanced all-wheel drive system, and robust capability."},
                "AOE Volt": {"type": "Compact EV", "powertrain": "EV", "features": "instant torque, zero-emission performance, and intelligent connectivity features."}
            }


        logging.info("Successfully fetched and parsed vehicle data.")
        return vehicles_data

    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching vehicle data from website: {e}", exc_info=True)
        # Fallback to hardcoded defaults on network/HTTP error
        return {
            "AOE Apex": {"type": "Sedan", "powertrain": "Gasoline", "features": "sleek design, powerful performance, and advanced safety features."}, # Corrected fallback
            "AOE Thunder": {"type": "SUV", "powertrain": "Gasoline", "features": "bold design, advanced all-wheel drive system, and robust capability."},
            "AOE Volt": {"type": "Compact EV", "powertrain": "EV", "features": "instant torque, zero-emission performance, and intelligent connectivity features."}
        }
    except Exception as e:
        logging.error(f"Error parsing vehicle data from website: {e}", exc_info=True)
        # Fallback to hardcoded defaults on parsing error
        return {
            "AOE Apex": {"type": "Sedan", "powertrain": "Gasoline", "features": "sleek design, powerful performance, and advanced safety features."}, # Corrected fallback
            "AOE Thunder": {"type": "SUV", "powertrain": "Gasoline", "features": "bold design, advanced all-wheel drive system, and robust capability."},
            "AOE Volt": {"type": "Compact EV", "powertrain": "EV", "features": "instant torque, zero-emission performance, and intelligent connectivity features."}
        }

# Run database initialization and initial data fetch on app startup
@app.on_event("startup")
async def startup_event():
    init_db()
    global cached_aoe_vehicles_data, LAST_DATA_REFRESH_TIME
    logging.info("Performing initial vehicle data fetch on startup...")
    cached_aoe_vehicles_data = fetch_aoe_vehicle_data_from_website()
    if cached_aoe_vehicles_data:
        LAST_DATA_REFRESH_TIME = time.time()
        logging.info(f"Initial vehicle data fetched. {len(cached_aoe_vehicles_data)} vehicles loaded.")
    else:
        logging.error("Failed to fetch initial vehicle data from website. Relying on hardcoded fallbacks.")


# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Email config
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 0))
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
TEAM_EMAIL = os.getenv("TEAM_EMAIL") # This is used for sending internal notifications

# OpenAI config
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logging.error("OPENAI_API_KEY environment variable is not set.")
    # Consider raising an exception or handling this more gracefully in production
    raise ValueError("OpenAI API key not found. Please set OPENAI_API_KEY in your .env file.") # Added this for stronger error handling
client = OpenAI(api_key=OPENAI_API_KEY)

# --- DEBUG PRINTS (REMOVE FOR PRODUCTION) ---
print(f"DEBUG: Application Starting Up - {datetime.now()}")
print(f"DEBUG: Loaded EMAIL_HOST: '{EMAIL_HOST}'")
print(f"DEBUG: Loaded EMAIL_PORT: '{EMAIL_PORT}' (Type: {type(EMAIL_PORT)})")
print(f"DEBUG: Loaded EMAIL_ADDRESS: '{EMAIL_ADDRESS}'")
print(f"DEBUG: Loaded TEAM_EMAIL: '{TEAM_EMAIL}'")
# print(f"DEBUG: Loaded EMAIL_PASSWORD: '{EMAIL_PASSWORD}'") # !!! DO NOT UNCOMMENT THIS IN PRODUCTION !!!
print(f"DEBUG: Loaded OPENAI_API_KEY (first 5 chars): '{OPENAI_API_KEY[:5] if OPENAI_API_KEY else 'None'}'")
# --- END DEBUG PRINTS ---


@app.post("/webhook/testdrive")
async def testdrive_webhook(request: Request):
    logging.info("Webhook /testdrive received a request.")
    data = await request.json()

    logging.debug(f"Received data: {data}")

    full_name = data.get("fullName", "")
    email = data.get("email", "")
    phone = data.get("phone", "")
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

    # Check if data needs refresh before processing (simple caching mechanism)
    if time.time() - LAST_DATA_REFRESH_TIME > REFRESH_INTERVAL_SECONDS:
        logging.info("Refreshing cached vehicle data...")
        new_data = fetch_aoe_vehicle_data_from_website()
        if new_data: # Only update if new data was successfully fetched
            cached_aoe_vehicles_data = new_data
            LAST_DATA_REFRESH_TIME = time.time()
            logging.info("Cached vehicle data refreshed.")
        else:
            logging.warning("Failed to refresh vehicle data. Continuing with old cached data.")
    
    # Get specific vehicle info from cache; fallback to generic if not found
    vehicle_info = cached_aoe_vehicles_data.get(vehicle, {
        "type": "vehicle", # Generic default
        "powertrain": "advanced performance", # Generic default
        "features": "cutting-edge technology and futuristic design." # Generic default
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
    lead_score = "Unknown"

    try:
        if not OPENAI_API_KEY or not client:
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
        """
        subject_completion = client.chat.com.pletion.create(
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
        - Phone: {phone}
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
            * Weave in the {vehicle}'s key features ({chosen_aoe_features}), **explicitly mentioning its {vehicle_type} and {powertrain_type}**.
            * Focus on the *experience* and *benefits*.
            * **Crucial Comparison Logic:**
                * If `current_vehicle` is provided (and not 'no vehicle' or 'exploring'), subtly position the {vehicle} as a significant, transformative upgrade. Example: "As a {current_vehicle} owner, prepare to experience the next level of automotive innovation with the AOE {vehicle} {vehicle_type}, a remarkable {powertrain_type} vehicle that offers..." **Avoid any blunt or negative comparisons.**
                * If `current_vehicle` is 'no vehicle' or 'exploring', frame it as an exciting new kind of driving experience, a leap into advanced {powertrain_type} {vehicle_type} technology, or an opportunity to discover what makes AOE Motors unique.

        * **Paragraph 3 (Personalized Support for Your Journey - CRITICAL IMPLICIT FIX):**
            * This paragraph will *exclusively* address the '{time_frame}' for *purchase intent*.
            * **CRITICAL: This paragraph MUST NOT explicitly mention '{time_frame}' or any specific timeframe (e.g., '0-3 months', '3-6 months', '6-12 months', 'exploring'). Convey the time frame *implicitly* through the tone and focus of the support offered, using phrasing that aligns with their readiness.**
            * If `time_frame` is '0-3-months': Emphasize AOE Motors' readiness to support their swift decision, hinting at tailored support and exclusive opportunities for those ready to embrace the future soon.
                * *Example Implicit Phrasing:* "We understand you're ready to make a swift decision, and our team is poised to offer tailored support and exclusive opportunities as you approach ownership."
            * If `time_frame` is '3-6-months' or '6-12-months': Focus on offering continued guidance and resources throughout their decision-making journey, highlighting that you're ready to assist them when they're closer to a purchase decision, providing resources for further exploration.
                * *Example Implicit Phrasing:* "As you carefully consider your options over the coming months, we are committed to providing comprehensive support and insights to help you make an informed choice."
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
        body_completion = client.chat.completions.create(
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


        # --- 3. Simple Lead Scoring ---
        logging.info(f"Attempting to classify lead hotness for {email} using OpenAI...")
        lead_scoring_prompt = f"""
        Classify the lead hotness for a customer based on their purchase time frame and current vehicle.

        **Customer Details:**
        - Purchase Time Frame: {time_frame}
        - Customer's Current Vehicle: {current_vehicle}

        **Instructions:**
        - Classify as 'Hot', 'Warm', or 'Cold'.
        - 'Hot': Purchase time frame '0-3-months', especially if they have a current vehicle they might be upgrading from.
        - 'Warm': Purchase time frame '3-6-months' or '6-12-months'.
        - 'Cold': Purchase time frame 'exploring' or no specific time frame.
        - Only output the classification (e.g., 'Hot', 'Warm', 'Cold').
        """
        lead_score_completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an AI assistant for lead classification."},
                {"role": "user", "content": lead_scoring_prompt}
            ],
            temperature=0.0,
            max_tokens=10
        )
        lead_score = lead_score_completion.choices[0].message.content.strip()
        logging.info(f"Lead Score for {email}: '{lead_score}'")


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
            team_subject = f"NEW TEST DRIVE LEAD: {full_name} ({lead_score} Lead)"
            # Note: For team email, it's safer to send plain text as HTML might render weirdly in logs/simple email clients
            team_body = f"""
            Dear Team,

            A new test drive booking has been received.

            **Customer Details:**
            - Name: {full_name}
            - Email: {email}
            - Phone: {phone}
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
            """
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

        # --- Save to Database ---
        try:
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO bookings (full_name, email, phone, vehicle, booking_date, location, current_vehicle, time_frame, generated_subject, generated_body, lead_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (full_name, email, phone, vehicle, date, location, current_vehicle, time_frame, generated_subject, generated_body, lead_score))
            conn.commit()
            conn.close()
            logging.info(f"Booking for {email} saved to database with lead score '{lead_score}'.")
        except Exception as db_e:
            logging.error(f"Failed to save booking to database for {email}: {db_e}", exc_info=True)


    except Exception as e:
        logging.error(f"❌ Failed to process request or send email to {email}: {e}", exc_info=True)
        # Return an error status if any part of the process fails
        return {"status": "error", "message": f"Failed to process test drive booking: {str(e)}"}

    return {"status": "success", "message": "Test drive data processed, emails sent, and lead scored."}
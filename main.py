import requests
from bs4 import BeautifulSoup
import time
import json
from fastapi import FastAPI, Request, HTTPException
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
LAST_DATA_REFRESH_TIME = 0
REFRESH_INTERVAL_SECONDS = 4 * 3600 # Refresh every 4 hours (adjust as needed, e.g., 24*3600 for daily)

# DUMMY RESOURCE LINKS (for demonstration purposes)
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

def fetch_aoe_vehicle_data_from_website():
    """
    Fetches vehicle data by scraping the AOE Motors website.
    This implementation attempts to find structured features and specifications.
    """
    url = "https://aoe-motors.lovable.app/#vehicles"
    logging.info(f"Attempting to fetch vehicle data from {url}...")
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        vehicles_data = {}
        
        # Adjust these selectors based on the actual HTML structure of your website
        vehicle_cards = soup.find_all('div', class_=lambda x: x and ('bg-white' in x or 'shadow' in x) and 'p-6' in x)
        
        if not vehicle_cards:
            logging.warning("No specific vehicle cards found by common styling. Trying more generic 'section' tags.")
            vehicle_cards = soup.find_all('section')

        for card in vehicle_cards:
            name_tag = card.find(['h2', 'h3', 'h4'], string=lambda text: text and "AOE" in text)
            if name_tag:
                name = name_tag.get_text(strip=True)
                vehicle_type = "Vehicle" # Default
                powertrain = "Unknown" # Default
                features_list = []

                # --- NEW: Extract Powertrain and Vehicle Type from Specifications Tab ---
                spec_tab_button = card.find('button', string='Specifications')
                spec_content_div = None
                if spec_tab_button:
                    # Find the content div associated with the Specifications tab
                    # This often involves navigating siblings or parents
                    potential_spec_div = spec_tab_button.find_parent().find_next_sibling('div')
                    if potential_spec_div:
                        spec_content_div = potential_spec_div
                
                if spec_content_div:
                    spec_text = spec_content_div.get_text().lower()
                    if "electric" in spec_text or "dual electric motors" in spec_text:
                        powertrain = "Electric"
                    elif "turbocharged" in spec_text or "v6" in spec_text or "i4" in spec_text or "engine" in spec_text:
                        powertrain = "Gasoline"
                    else:
                        powertrain = "Hybrid" # A generic fallback for other types
                
                # Derive vehicle type based on visual clues (e.g., text near name or specific class)
                # This is still heuristic and may need refinement if HTML changes.
                type_tag = card.find('p', class_='text-gray-600') # Common class for type description
                if type_tag and ("sedan" in type_tag.get_text().lower()):
                    vehicle_type = "Luxury Sedan"
                elif type_tag and ("suv" in type_tag.get_text().lower()):
                    vehicle_type = "Performance SUV"
                elif type_tag and ("electric" in type_tag.get_text().lower() and "compact" in type_tag.get_text().lower()):
                    vehicle_type = "Electric Compact"
                elif "Apex" in name: # Fallback if not found in specific tag
                    vehicle_type = "Luxury Sedan"
                elif "Thunder" in name:
                    vehicle_type = "Performance SUV"
                elif "Volt" in name:
                    vehicle_type = "Electric Compact"


                # --- Existing Feature Scraping Logic ---
                features_tab_button = card.find('button', string='Features')
                features_content_div = None
                if features_tab_button:
                    next_div = features_tab_button.find_parent().find_next_sibling('div')
                    if next_div and next_div.find('ul'):
                        features_content_div = next_div
                    else:
                        features_content_div = card # Fallback to card if specific feature div not found
                else:
                    features_content_div = card # Fallback if no features button

                if features_content_div:
                    for li in features_content_div.find_all('li'):
                        feature_text = li.get_text(strip=True)
                        if feature_text and len(feature_text) > 5: # Basic filter for meaningful features
                            features_list.append(feature_text)
                
                features_str = ", ".join(features_list) if features_list else f"cutting-edge technology and a luxurious experience, including {vehicle_type} specific enhancements."

                # Refined Fallback to general descriptions if scraping yields little or nothing
                if not features_list or len(features_list) < 3:
                    if "Apex" in name:
                        features_str = "Massage Seats with Memory Foam, Panoramic Glass Roof with Electrochromic Dimming, Level 3 Autonomous Driving, Wireless Phone Charging & Connectivity, Advanced Air Purification System, Heated & Ventilated Seats."
                    elif "Thunder" in name:
                        features_str = "Advanced Terrain Management System, Adaptive All Suspension, 360 Surround View Camera, Towing Capacity: 7,500 lbs, Sport Track Mode, Premium Brembo Braking System, Wade Sensing Technology, Dual-Zone Climate Control."
                    elif "Volt" in name:
                        features_str = "Ultra-Fast 350kW DC Charging, Advanced Autopilot with AI, Solar Panel Integration, Vehicle-to-Grid (V2G) Technology, Over-the-Air Software Updates, Regenerative Braking System, Smart Climate Pre-conditioning, Wireless Charging Pad."

                vehicles_data[name] = {
                    "type": vehicle_type,
                    "powertrain": powertrain,
                    "features": features_str
                }
        
        if not vehicles_data:
            logging.warning("No specific AOE vehicle data found by scraping. Using hardcoded defaults as fallback.")
            vehicles_data = {
                "AOE Apex": {"type": "Luxury Sedan", "powertrain": "Gasoline", "features": "Massage Seats with Memory Foam, Panoramic Glass Roof with Electrochromic Dimming, Level 3 Autonomous Driving, Wireless Phone Charging & Connectivity, Advanced Air Purification System, Heated & Ventilated Seats."},
                "AOE Thunder": {"type": "Performance SUV", "powertrain": "Gasoline", "features": "Advanced Terrain Management System, Adaptive All Suspension, 360 Surround View Camera, Towing Capacity: 7,500 lbs, Sport Track Mode, Premium Brembo Braking System, Wade Sensing Technology, Dual-Zone Climate Control."},
                "AOE Volt": {"type": "Electric Compact", "powertrain": "Electric", "features": "Ultra-Fast 350kW DC Charging, Advanced Autopilot with AI, Solar Panel Integration, Vehicle-to-Grid (V2G) Technology, Over-the-Air Software Updates, Regenerative Braking System, Smart Climate Pre-conditioning, Wireless Charging Pad."}
            }

        logging.info("Successfully fetched and parsed vehicle data.")
        return vehicles_data

    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching vehicle data from website: {e}", exc_info=True)
        # Fallback to hardcoded values for robustness
        return {
            "AOE Apex": {"type": "Luxury Sedan", "powertrain": "Gasoline", "features": "Massage Seats with Memory Foam, Panoramic Glass Roof with Electrochromic Dimming, Level 3 Autonomous Driving, Wireless Phone Charging & Connectivity, Advanced Air Purification System, Heated & Ventilated Seats."},
            "AOE Thunder": {"type": "Performance SUV", "powertrain": "Gasoline", "features": "Advanced Terrain Management System, Adaptive All Suspension, 360 Surround View Camera, Towing Capacity: 7,500 lbs, Sport Track Mode, Premium Brembo Braking System, Wade Sensing Technology, Dual-Zone Climate Control."},
            "AOE Volt": {"type": "Electric Compact", "powertrain": "Electric", "features": "Ultra-Fast 350kW DC Charging, Advanced Autopilot with AI, Solar Panel Integration, Vehicle-to-Grid (V2G) Technology, Over-the-Air Software Updates, Regenerative Braking System, Smart Climate Pre-conditioning, Wireless Charging Pad."}
        }
    except Exception as e:
        logging.error(f"Error parsing vehicle data from website: {e}", exc_info=True)
        # Fallback to hardcoded values for robustness
        return {
            "AOE Apex": {"type": "Luxury Sedan", "powertrain": "Gasoline", "features": "Massage Seats with Memory Foam, Panoramic Glass Roof with Electrochromic Dimming, Level 3 Autonomous Driving, Wireless Phone Charging & Connectivity, Advanced Air Purification System, Heated & Ventilated Seats."},
            "AOE Thunder": {"type": "Performance SUV", "powertrain": "Gasoline", "features": "Advanced Terrain Management System, Adaptive All Suspension, 360 Surround View Camera, Towing Capacity: 7,500 lbs, Sport Track Mode, Premium Brembo Braking System, Wade Sensing Technology, Dual-Zone Climate Control."},
            "AOE Volt": {"type": "Electric Compact", "powertrain": "Electric", "features": "Ultra-Fast 350kW DC Charging, Advanced Autopilot with AI, Solar Panel Integration, Vehicle-to-Grid (V2G) Technology, Over-the-Air Software Updates, Regenerative Braking System, Smart Climate Pre-conditioning, Wireless Charging Pad."}
        }

# Run initial data fetch on app startup
@app.on_event("startup")
async def startup_event():
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
    raise ValueError("OpenAI API key not found. Please set OPENAI_API_KEY in your .env file or Render environment.")
client = OpenAI(api_key=OPENAI_API_KEY)

# --- DEBUG PRINTS (REMOVE FOR PRODUCTION) ---
print(f"DEBUG: Application Starting Up - {datetime.now()}")
print(f"DEBUG: Loaded EMAIL_HOST: '{EMAIL_HOST}'")
print(f"DEBUG: Loaded EMAIL_PORT: '{EMAIL_PORT}' (Type: {type(EMAIL_PORT)})")
print(f"DEBUG: Loaded EMAIL_ADDRESS: '{EMAIL_ADDRESS}'")
print(f"DEBUG: Loaded TEAM_EMAIL: '{TEAM_EMAIL}'")
print(f"DEBUG: Loaded OPENAI_API_KEY (first 5 chars): '{OPENAI_API_KEY[:5] if OPENAI_API_KEY else 'None'}'")
print(f"DEBUG: Supabase URL (first 5 chars): '{SUPABASE_URL[:5] if SUPABASE_URL else 'None'}'")
print(f"DEBUG: Supabase Key (first 5 chars): '{SUPABASE_KEY[:5] if SUPABASE_KEY else 'None'}'")
# --- END DEBUG PRINTS ---


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
        - **Do NOT confuse 'Vehicle Type' with 'Powertrain Type'.** For {vehicle}, the vehicle type is {vehicle_type} and the powertrain is {powertrain_type}.
        """
        subject_completion = client.chat.completions.create(
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

@app.get("/")
async def read_root():
    """Root endpoint for the API."""
    return {"message": "Welcome to AOE Motors Test Drive API. Send a POST request to /webhook/testdrive to book a test drive."}
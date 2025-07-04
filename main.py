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
            logging.error(f"❌ Failed to update booking {request_body.request_id}. Response: {response}")
            raise HTTPException(status_code=500, detail="Failed to update booking.")
    except Exception as e:
        logging.error(f"🚨 Error updating booking {request_body.request_id}: {e}", exc_info=True)
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

        msg_customer = MIMEMultipart()
        msg_customer["From"] = EMAIL_ADDRESS
        msg_customer["To"] = request_body.customer_email
        msg_customer["Subject"] = generated_subject
        msg_customer.attach(MIMEText(generated_body, "html"))

        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
            logging.debug(f"Attempting to connect to SMTP server for follow-up email: {EMAIL_HOST}:{EMAIL_PORT}")
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg_customer)
            logging.info(f"✅ Follow-up email successfully sent to {request_body.customer_email} (Subject: '{generated_subject}').")

        return {"status": "success", "message": "Follow-up email drafted and sent successfully."}

    except Exception as e:
        logging.error(f"🚨 An unexpected error occurred during follow-up email processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

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
        youtube_link = resources["youtube_link"]
        pdf_link = resources["pdf_link"]


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
        - YouTube Link: {youtube_link}
        - PDF Link: {pdf_link}

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

        * **Paragraph 2 (Vehicle Features & Persuasive Comparison - Simplified Language):**
            * From the provided {chosen_aoe_features}, **select and highlight only 2-3 MOST EXCITING and UNIQUE features**.
            * **Crucially, translate any technical jargon into simple, benefit-oriented language, focusing on what the feature *does for the driver* and the *experience* it provides.** For example, instead of "V8 Twin-Turbo Engine," phrase it as "a powerful engine designed for exhilarating acceleration." If the feature is "Advanced driver-assistance systems (ADAS)", explain its benefit like "advanced safety features that provide peace of mind." **Do NOT use acronyms without immediate, simple explanation.**
            * Integrate these naturally into the paragraph, explicitly mentioning its {vehicle_type} and {powertrain_type}. Do NOT simply list features or include more than 3 distinct features in this paragraph.
            * **Crucial Comparison Logic:**
                * If `current_vehicle` is provided (and not 'No-vehicle' or 'exploring'), subtly position the {vehicle} as a significant, transformative upgrade. Example: "As a {current_vehicle} owner, prepare to experience the next level of automotive innovation with the AOE {vehicle} {vehicle_type}, a remarkable {powertrain_type} vehicle that offers..." **Avoid any blunt or negative comparisons.**
                * If `current_vehicle` is 'No-vehicle' or 'exploring', frame it as an exciting new kind of driving experience, a leap into advanced {powertrain_type} {vehicle_type} technology, or an opportunity to discover what makes AOE Motors unique.

        * **Paragraph 3 (Overall Experience & Broader Benefits - NO new features):**
            * This paragraph should focus on the *overall driving experience* of the {vehicle} or the * broader benefits* of choosing an AOE vehicle.
            * **Do NOT introduce any new specific features in this paragraph.** This paragraph is for a more general, appealing description.
            * If `current_vehicle` is 'exploring', this paragraph can reinforce the idea of discovery, reliability, and the unique possibilities the {vehicle} offers for their lifestyle.
            * Example: "<p>Beyond its impressive features, the AOE {vehicle} is engineered for a harmonious blend of exhilarating performance and sophisticated comfort, ensuring every drive is a pleasure.</p>" (This is an example, LLM should adapt.)

        * **Paragraph 4 (Personalized Support for Your Journey - CRITICAL IMPLICIT FIX for 'exploring'):**
            * This paragraph will *exclusively* address the '{time_frame}' for *purchase intent*.
            * **CRITICAL: This paragraph MUST NOT explicitly mention '{time_frame}' or any specific timeframe (e.g., '0-3 months', '3-6 months', '6-12 months', 'exploring'). Convey the time frame *implicitly* through the tone and focus of the support offered, using phrasing that aligns with their readiness.**
            * **Do NOT use any phrasing that implies urgency or a swift decision for 'exploring'.**
            * If `time_frame` is '0-3-months': Emphasize AOE Motors' readiness to support their swift decision, hinting at tailored support and exclusive opportunities for those ready to embrace the future soon.
                * *Example Implicit Phrasing:* "We understand you're ready to make a swift decision, and our team is poised to offer tailored support and exclusive opportunities as you approach ownership."
            * If `time_frame` is '3-6-months' or '6-12-months': Focus on offering continued guidance and resources throughout their decision-making journey, highlighting that you're ready to assist them when they're closer to a purchase decision, providing resources for further exploration.
                * *Example Implicit Phrasing:* "As you carefully consider your options over the coming months, we are committed to providing comprehensive support and insights to help you make an informed choice."
            * If `time_frame` is 'exploring': Maintain a welcoming, low-pressure tone, focusing purely on discovery and making the experience informative and enjoyable for their future consideration, without any hint of urgency or swift decisions. The goal is to provide resources and be available for questions at their pace.
                * *Example Implicit Phrasing (stronger emphasis for 'exploring', and explicit negative constraint for LLM):* "We are delighted to support you at your own pace as you explore the possibilities. There's no pressure; our team is here to provide any information or answer any questions you may have as you consider your options for the future." **Absolutely avoid any phrasing like 'swift decision', 'ready to make a purchase', 'approach ownership' for 'exploring' customers.**

        * **Paragraph 5 (Valuable Resources):**
            * Provide a sentence encouraging them to learn more.
            * Include two distinct hyperlinks: one for the `YouTube Link` (e.g., "Watch the AOE {vehicle} Overview Video") and one for the `PDF Guide Link` (e.g., "Download the AOE {vehicle} Guide (PDF)").
            * Example: "<p>To learn even more about the {vehicle}, we invite you to watch our detailed video: <a href=\"{youtube_link}\">Watch the AOE {vehicle} Overview Video</a> and download the comprehensive guide: <a href=\"{pdf_link}\">Download the AOE {vehicle} Guide (PDF)</a>.</p>"

        * **Paragraph 6 (Call to Action & Closing):**
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
        generated_subject = f"AOE Test Drive Confirmed! Get Ready for Your {vehicle} Experience"
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
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

# Run database initialization on app startup
@app.on_event("startup")
async def startup_event():
    init_db()

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

# Vehicle feature mapping (from your original script)
aoe_features = {
    "AOE Apex": "sleek design, ultra-efficient EV range, and adaptive cruise control.",
    "AOE Thunder": "bold design, sedan-class refinement, and advanced all-wheel drive system.",
    "AOE Volt": "instant torque, zero-emission performance, and intelligent connectivity features."
}

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

    chosen_aoe_features = aoe_features.get(vehicle, "cutting-edge technology and futuristic design.")

    # Determine tone based on time frame for email body and subject
    tone_instruction_body = "The tone should be enthusiastic and persuasive, highlighting immediate benefits."
    tone_instruction_subject = "Use a highly persuasive and exciting tone."
    if time_frame == "0-3-months": # Corrected from "0-3-months" to match common input, if your frontend sends "0-3-months"
        tone_instruction_body = "The tone should be highly persuasive, emphasizing immediate benefits and limited-time offers."
        tone_instruction_subject = "Use a highly persuasive and exciting tone, suggesting urgency."
    elif time_frame == "3-6-months":
        tone_instruction_body = "The tone should be informative and encouraging, focusing on future benefits and guiding them through the next steps."
        tone_instruction_subject = "Use an informative and encouraging tone, highlighting key features."
    elif time_frame == "6-12-months":
        tone_instruction_body = "The tone should be informative and helpful, inviting further exploration and offering detailed insights."
        tone_instruction_subject = "Use an informative and helpful tone, suggesting further research."
    elif time_frame == "exploring":
        tone_instruction_body = "The tone should be welcoming and inviting, providing general information without pressure and encouraging casual exploration."
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
        - Vehicle: {vehicle}
        - Test Drive Date: {formatted_date}
        - Location: {location}
        - Customer's Current Vehicle: {current_vehicle}
        - Purchase Time Frame: {time_frame}

        **Instructions:**
        - {tone_instruction_subject}
        - Keep it brief (under 15 words).
        - Do NOT include "Subject:" or any salutation/closing in the output.
        - Example: "Your Apex Test Drive is Confirmed!" or "Experience the Volt: Your Test Drive Awaits!"
        """
        subject_completion = client.chat.completions.create(
            model="gpt-3.5-turbo", # You can choose a different model like "gpt-4o" for better quality if available and cost allows
            messages=[
                {"role": "system", "content": "You are a helpful assistant for AOE Motors, specializing in catchy email subjects."},
                {"role_name": "user", "content": subject_prompt}
            ],
            temperature=0.7,
            max_tokens=50
        )
        generated_subject = subject_completion.choices[0].message.content.strip()
        logging.debug(f"Generated Subject: '{generated_subject}'")


        # --- 2. Generate Complete Email Body ---
        logging.info(f"Attempting to generate email body for {email} using OpenAI...")
        body_prompt = f"""
        You are an AI assistant for AOE Motors, crafting a personalized test drive confirmation email.

        **Goal:** Generate the complete body of a professional and engaging email based on the provided customer information and test drive details.

        **Customer Details:**
        - Full Name: {full_name}
        - Email: {email}
        - Phone: {phone}
        - Vehicle of Interest: {vehicle}
        - Test Drive Date: {formatted_date}
        - Test Drive Location: {location}
        - Customer's Current Vehicle: {current_vehicle} (if 'no vehicle', indicate they are exploring new options)
        - Purchase Time Frame: {time_frame}

        **AOE Vehicle Features (for {vehicle}):**
        - {chosen_aoe_features}

        **Instructions for Email Content:**
        1.  Start with a warm greeting to {full_name}.
        2.  Thank them for booking the test drive for the {vehicle} at the {location} location on {formatted_date}.
        3.  **Current Vehicle Comparison:**
            - If the customer has a `current_vehicle` (not 'no vehicle'), gently highlight how the {vehicle}'s features (mentioned above) are a significant upgrade or offer distinct advantages compared to what someone owning a {current_vehicle} might experience. Rely on general knowledge for {current_vehicle} features; avoid highly specific technical comparisons unless explicitly stated in your provided AOE features.
            - If `current_vehicle` is 'no vehicle', phrase it as an exciting opportunity for someone new to (or upgrading to) an advanced vehicle.
        4.  **Tone Adjustment based on Time Frame:**
            - {tone_instruction_body}
        5.  **Personalization by Location:** Briefly mention something positive or relevant about the {location} if appropriate, or simply integrate it smoothly into the sentence structure.
        6.  Conclude with a warm closing from "Team AOE Motors".
        7.  **Format:** Use paragraphs for readability. Do NOT include subject line or sender/recipient details, only the body of the email.
        """
        body_completion = client.chat.completions.create(
            model="gpt-3.5-turbo", # Consider "gpt-4o" for better quality if available and cost allows
            messages=[
                {"role": "system", "content": "You are a helpful assistant for AOE Motors."},
                {"role_name": "user", "content": body_prompt}
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
                {"role_name": "user", "content": lead_scoring_prompt}
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
        msg_customer.attach(MIMEText(generated_body, "html")) # Changed to 'html' in case OpenAI generates HTML tags

        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
            logging.debug(f"Attempting to connect to SMTP server for customer email: {EMAIL_HOST}:{EMAIL_PORT}")
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg_customer)
            logging.info(f"✅ Customer email successfully sent to {email} (Subject: '{generated_subject}', Score: '{lead_score}').")

        # --- Email Sending to Team ---
        if TEAM_EMAIL and EMAIL_ADDRESS and EMAIL_PASSWORD: # Ensure TEAM_EMAIL is configured
            team_subject = f"NEW TEST DRIVE LEAD: {full_name} ({lead_score} Lead)"
            team_body = f"""
            Dear Team,

            A new test drive booking has been received.

            **Customer Details:**
            - Name: {full_name}
            - Email: {email}
            - Phone: {phone}
            - Vehicle: {vehicle}
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
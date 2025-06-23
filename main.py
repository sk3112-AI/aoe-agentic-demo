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
# Ensure logs are written to stdout/stderr in production environments like Render
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

# Vehicle feature mapping
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
    if time_frame == "0-3-months":
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
                {"role": "user", "content": subject_prompt}
            ],
            temperature=0.7,
            max_tokens=50
        )
        generated_subject = subject_completion.choices[0].message.content.strip()
        logging.debug(f"Generated Subject: '{generated_subject}'")


        # --- 2. Generate Complete Email Body (UPDATED PROMPT) ---
        logging.info(f"Attempting to generate email body for {email} using OpenAI...")
        body_prompt = f"""
        You are an AI assistant for AOE Motors, crafting a personalized test drive confirmation email.

        **Goal:** Generate the complete body of a professional, engaging, and highly persuasive email with a natural, story-like flow. The email should sound human-written, be easy to read, properly spaced out, concise, and relevant, avoiding any unnecessary length or fluff.

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
        - {chosen_aoe_features} (e.g., sleek design, ultra-efficient EV range, adaptive cruise control)

        **Instructions for Email Content:**
        1.  Start with an exciting and warm greeting to {full_name}. Confirm the test drive details (vehicle, date, location) immediately, emphasizing the excitement.
        2.  **Crucial:** **ABSOLUTELY DO NOT include the subject line or any "Subject:" prefix in the email body.** The subject is handled separately.
        3.  **Narrative Feature Integration & Elegant Comparison:**
            - Weave the {vehicle}'s key features ({chosen_aoe_features}) into one or two flowing paragraphs. Focus on the *experience* and *benefits* these features provide.
            - If `current_vehicle` is provided (not 'no vehicle' or 'exploring'), subtly integrate a comparison that positions the {vehicle} as a significant upgrade or "next level" experience. For example, "As a {current_vehicle} owner, prepare to experience the next level of automotive innovation" or "If you're upgrading from a {current_vehicle}, discover how the {vehicle} elevates your drive." Avoid blunt or direct negative comparisons. Make it about transformation and advancement.
            - If `current_vehicle` is 'no vehicle' or 'exploring', frame it as an exciting opportunity for a new kind of driving experience or a leap into advanced electric vehicles.
        4.  **Time Frame Personalization (Seamless Paragraph):**
            - Incorporate the message for the '{time_frame}' without a separate sub-heading.
            - **Important:** The `time_frame` refers to the customer's *purchase intent/readiness*, not the test drive date. Link it to relevant benefits or support for their *purchase journey*.
            - If `time_frame` is '0-3-months': Emphasize that this test drive is an ideal step for their immediate purchase plans, hinting at limited-time offers, exclusive benefits, and an unparalleled ownership experience for those ready to embrace the future now. Frame it as the perfect moment to align their test drive experience with their upcoming purchase.
            - If `time_frame` is '3-6-months' or '6-12-months': Focus on offering continued support and guidance throughout their decision-making journey, highlighting that you're ready to assist them when they're closer to a purchase decision.
            - If `time_frame` is 'exploring': Maintain a welcoming and inviting tone, focusing on discovery, exploration, and making the experience pressure-free, without linking it to the test drive's timing.
        5.  Conclude with a clear and helpful call to action for any questions, and express eagerness for their visit.
        6.  End with a warm closing from "Team AOE Motors".
        7.  **CRITICAL Formatting for Readability and Spacing:**
            - **Immediately after the greeting, use a double newline (`\n\n`) to start a new paragraph.**
            - **ALWAYS separate distinct thoughts or sections with a double newline (`\n\n`) to create clear, visually distinct paragraphs.**
            - **Each paragraph should be short and focused (2-4 sentences max).**
            - **The entire email should consist of 4-6 short paragraphs for optimal readability.**
            - Avoid long, dense blocks of text at all costs. Do NOT include any section dividers (like ---).
        """
        body_completion = client.chat.completions.create(
            model="gpt-3.5-turbo", # You can choose a different model like "gpt-4o" for better quality if available and cost allows
            messages=[
                {"role": "system", "content": "You are a helpful assistant for AOE Motors, crafting personalized, persuasive, human-like, and well-formatted test drive confirmation emails. Focus solely on the email body content."},
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
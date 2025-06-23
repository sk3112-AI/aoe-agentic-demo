from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from datetime import datetime
import logging
import sys # Import sys for direct stdout logging

# Load environment variables
load_dotenv()

# Logging setup
# IMPORTANT: For debugging on Render, we direct logs to sys.stdout
# This ensures they appear in Render's console logs regardless of default filters.
# Change level=logging.INFO or logging.WARNING for production to reduce verbosity.
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI()

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
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 0)) # Added default 0 for safer int conversion
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
TEAM_EMAIL = os.getenv("TEAM_EMAIL")

# --- START DEBUG PRINTS (REMOVE FOR PRODUCTION) ---
# These prints will show up in your Render logs immediately on startup
print(f"DEBUG: Application Starting Up - {datetime.now()}")
print(f"DEBUG: Loaded EMAIL_HOST: '{EMAIL_HOST}'")
print(f"DEBUG: Loaded EMAIL_PORT: '{EMAIL_PORT}' (Type: {type(EMAIL_PORT)})")
print(f"DEBUG: Loaded EMAIL_ADDRESS: '{EMAIL_ADDRESS}'")
# print(f"DEBUG: Loaded EMAIL_PASSWORD: '{EMAIL_PASSWORD}'") # !!! DO NOT UNCOMMENT THIS IN PRODUCTION !!!
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

    # Log received data (be cautious with sensitive data in production logs)
    logging.debug(f"Received data: {data}")

    full_name = data.get("fullName", "")
    email = data.get("email", "")
    phone = data.get("phone", "")
    vehicle = data.get("vehicle", "")
    date = data.get("date", "")
    location = data.get("location", "")
    current_vehicle = data.get("currentVehicle", "no vehicle").lower()
    time_frame = data.get("timeFrame", "exploring")

    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%B %d, %Y")
    except ValueError as e:
        logging.error(f"Error parsing date '{date}': {e}")
        return {"status": "error", "message": "Invalid date format"}

    # Subject and greeting
    subject = f"Thank you for booking your {vehicle} test drive"
    greeting = f"Hi {full_name},"

    # Vehicle-specific features
    features = aoe_features.get(vehicle, "cutting-edge technology and futuristic design.")

    # Comparison logic
    comparison = ""
    if current_vehicle != "no vehicle":
        comparison = f"As a {current_vehicle.title()} owner, you’ll notice the difference with the {vehicle}'s {features}"
    else:
        comparison = f"The {vehicle} offers {features} — a leap ahead in automotive innovation."

    # Urgency messaging
    urgency = ""
    if time_frame == "0-3-months":
        urgency = "Given your interest in purchasing soon, our team is ready to assist with exclusive purchase benefits tailored to you."
    elif time_frame in ["3-6-months", "6-12-months"]:
        urgency = "We’ll be here to support you throughout your decision-making journey."
    else:
        urgency = "Explore the future of driving at your own pace — we’re excited to have you experience the AOE difference."

    # Final email body
    body = f"""{greeting}

Thank you for booking your test drive of the {vehicle} at our {location} location on {formatted_date}.

{comparison}

{urgency}

We look forward to seeing you soon.

Warm regards,
Team AOE Motors"""

    try:
        logging.info(f"Attempting to send email to {email}...")

        # Construct and send email
        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        # Check if email config is missing before attempting connection
        if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD]):
            raise ValueError("One or more email configuration environment variables are missing or empty.")

        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
            logging.debug(f"Attempting to connect to SMTP server: {EMAIL_HOST}:{EMAIL_PORT}")
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            logging.debug(f"Successfully logged in as {EMAIL_ADDRESS}. Sending message...")
            server.send_message(msg)
            logging.info(f"✅ Email successfully sent to {email} for test drive on {date}")

    except Exception as e:
        # This will print the full exception object, which is very helpful
        logging.error(f"❌ Failed to send email to {email}: {e}", exc_info=True)
        # exc_info=True adds the full traceback to the log, which is invaluable

    return {"status": "success", "message": "Test drive data processed"}
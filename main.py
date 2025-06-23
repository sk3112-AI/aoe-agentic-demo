from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from datetime import datetime
import logging

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(filename="email_debug.log", level=logging.DEBUG, format="%(asctime)s - %(message)s")

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
EMAIL_PORT = int(os.getenv("EMAIL_PORT"))
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
TEAM_EMAIL = os.getenv("TEAM_EMAIL")

# Vehicle feature mapping
aoe_features = {
    "AOE Apex": "sleek design, ultra-efficient EV range, and adaptive cruise control.",
    "AOE Thunder": "bold design, sedan-class refinement, and advanced all-wheel drive system.",
    "AOE Volt": "instant torque, zero-emission performance, and intelligent connectivity features."
}

@app.post("/webhook/testdrive")
async def testdrive_webhook(request: Request):
    data = await request.json()
    full_name = data.get("fullName", "")
    email = data.get("email", "")
    phone = data.get("phone", "")
    vehicle = data.get("vehicle", "")
    date = data.get("date", "")
    location = data.get("location", "")
    current_vehicle = data.get("currentVehicle", "no vehicle").lower()
    time_frame = data.get("timeFrame", "exploring")

    date_obj = datetime.strptime(date, "%Y-%m-%d")
    formatted_date = date_obj.strftime("%B %d, %Y")

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
        # Construct and send email
        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)

        # Debug log
        logging.debug(f"✅ Email sent to {email} for test drive on {date} | Current Vehicle: {current_vehicle} | Time Frame: {time_frame}")

    except Exception as e:
        logging.error(f"❌ Failed to send email to {email}: {str(e)}")

    return {"status": "success", "message": "Test drive data processed"}

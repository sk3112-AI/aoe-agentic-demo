from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import smtplib
from email.message import EmailMessage
import os

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

app = FastAPI()

# Enable CORS for all origins (you can restrict this to specific domains)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define the request model
class TestDriveData(BaseModel):
    fullName: str
    email: str
    phone: str
    vehicle: str
    date: str
    location: str
    currentVehicle: str
    timeFrame: str

# Vehicle features from website
vehicle_features = {
    "AOE Apex": "sleek design, intuitive driver interface, and turbocharged efficiency",
    "AOE Thunder": "bold styling, advanced infotainment, and sport-performance tuning",
    "AOE Volt": "all-electric drivetrain, fast charging, and sustainable innovation"
}

def generate_email_content(data: TestDriveData):
    features = vehicle_features.get(data.vehicle, "cutting-edge features and next-gen performance")
    current_vehicle = data.currentVehicle.lower()
    timeframe = data.timeFrame.lower()

    if current_vehicle == "no vehicle":
        comparison_line = f"As you consider owning your first vehicle, the {data.vehicle} stands out with its {features}."
    else:
        comparison_line = f"As a {current_vehicle.title()} owner, you’ll find the {data.vehicle} offers a compelling upgrade with its {features}."

    if timeframe == "0-3-months":
        urgency_line = "Since you're planning to purchase soon, our team is ready to assist you with exclusive offers and a personalized buying experience."
    elif timeframe in ["3-6-months", "6-12-months"]:
        urgency_line = "We’d be happy to keep in touch and help you explore options as you get closer to your decision."
    else:
        urgency_line = "Feel free to explore the AOE range at your own pace — we’re here whenever you’re ready."

    email_body = f"""Subject: Thank you for booking your {data.vehicle} test drive

Hi {data.fullName},

Thank you for booking your test drive of the {data.vehicle} at our {data.location} location on {data.date}.

{comparison_line}
{urgency_line}

We look forward to seeing you soon.

Warm regards,  
Team AOE Motors
"""
    return email_body

@app.post("/webhook/testdrive")
async def testdrive_webhook(data: TestDriveData):
    # Generate email content
    body = generate_email_content(data)

    # Send Email
    msg = EmailMessage()
    msg["Subject"] = f"Thank you for booking your {data.vehicle} test drive"
    msg["From"] = os.getenv("EMAIL_SENDER")
    msg["To"] = data.email
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(os.getenv("EMAIL_SENDER"), os.getenv("EMAIL_PASSWORD"))
            smtp.send_message(msg)
        return {"message": "Email sent successfully"}
    except Exception as e:
        return {"error": str(e)}

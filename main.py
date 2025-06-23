
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate
import datetime
import uvicorn
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# ----------------------
# LangChain + OpenAI Setup
# ----------------------
llm = OpenAI(temperature=0.7)

prompt_template = PromptTemplate(
    input_variables=["vehicle", "location", "date", "current_vehicle", "time_frame"],
    template="""
    You are a persuasive automotive marketing assistant. Create a short, engaging, and personalized message for a customer who just booked a test drive.

    Customer currently drives: {current_vehicle}
    They are planning to purchase in: {time_frame}
    Interested Vehicle: {vehicle}
    Test Drive Location: {location}
    Preferred Date: {date}

    Highlight key features of the {vehicle} and compare subtly with {current_vehicle} if applicable. Be more persuasive if purchase time frame is short (0-3 months). Keep it human, personalized and natural.

    Output format:
    ---
    {vehicle} - Test Drive Confirmation

    Hi <customer_name>,

    <dynamic persuasive message>

    Best,
    AOE Motors
    """
)

# ----------------------
# FastAPI App Setup
# ----------------------
app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for now
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TestDriveRequest(BaseModel):
    fullName: str
    email: str
    phone: str
    vehicle: str
    date: str
    location: str
    currentVehicle: str
    timeFrame: str

# ----------------------
# Email Sending Function
# ----------------------
def send_email(to_email, subject, body):
    sender_email = os.getenv("EMAIL_ADDRESS")
    sender_password = os.getenv("EMAIL_PASSWORD")

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)

@app.post("/webhook/testdrive")
async def testdrive_handler(payload: TestDriveRequest):
    try:
        # Generate prompt
        prompt = prompt_template.format(
            vehicle=payload.vehicle,
            location=payload.location,
            date=payload.date,
            current_vehicle=payload.currentVehicle,
            time_frame=payload.timeFrame
        )

        ad_output = llm(prompt).strip()

        email_body = f"""Hi {payload.fullName},

{ad_output}

Best,
AOE Motors
        """

        # Send to customer
        send_email(
            to_email=payload.email,
            subject=f"Thank you for booking your AOE {payload.vehicle} test drive",
            body=email_body
        )

        # Send to internal marketing/sales team
        internal_email = os.getenv("TEAM_EMAIL") or "sales@aoemotors.com"
        internal_body = f"New Test Drive Lead:

Name: {payload.fullName}
Email: {payload.email}
Phone: {payload.phone}
Vehicle: {payload.vehicle}
Location: {payload.location}
Date: {payload.date}
Current Vehicle: {payload.currentVehicle}
Timeframe: {payload.timeFrame}

Generated Message:
{ad_output}"

        send_email(
            to_email=internal_email,
            subject=f"[New Lead] Test Drive - {payload.vehicle}",
            body=internal_body
        )

        return {
            "customer": payload.fullName,
            "vehicle": payload.vehicle,
            "location": payload.location,
            "preferred_date": payload.date,
            "generated_ad": ad_output,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/")
async def root():
    return {"message": "AOE Agentic AI Test Drive Service is running."}

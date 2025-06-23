
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate
import datetime
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
    template="""You are a persuasive automotive sales assistant. Create a short, engaging follow-up message for a customer who booked a test drive.

Vehicle: {vehicle}
Location: {location}
Date: {date}
Currently drives: {current_vehicle}
Purchase timeline: {time_frame}

Mention 2 key features of the {vehicle} from the AOE Motors lineup (Apex, Thunder, or Volt), and subtly compare with {current_vehicle} if applicable. If purchase timeline is within 3 months, use an encouraging and urgent tone. Otherwise, be friendly and informative.

Output:
<subject>
<message body>
"""
)

# ----------------------
# FastAPI App Setup
# ----------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
        prompt = prompt_template.format(
            vehicle=payload.vehicle,
            location=payload.location,
            date=payload.date,
            current_vehicle=payload.currentVehicle,
            time_frame=payload.timeFrame
        )
        ad_output = llm(prompt).strip()

        if "\n" in ad_output:
            subject, body = ad_output.split("\n", 1)
        else:
            subject, body = "Thank you for booking your test drive", ad_output

        email_body = f"""Hi {payload.fullName},

{body.strip()}

We'll get in touch soon to confirm your test drive appointment.

Best,  
Team AOE Motors"""

        send_email(
            to_email=payload.email,
            subject=subject.strip(),
            body=email_body
        )

        internal_email = os.getenv("TEAM_EMAIL") or "sales@aoemotors.com"
        internal_body = f"New Test Drive Lead:\n\nName: {payload.fullName}\nEmail: {payload.email}\nPhone: {payload.phone}\nVehicle: {payload.vehicle}\nLocation: {payload.location}\nDate: {payload.date}\nCurrently drives: {payload.currentVehicle}\nPurchase timeframe: {payload.timeFrame}\n\nGenerated Message:\n{ad_output}"

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
            "current_vehicle": payload.currentVehicle,
            "timeframe": payload.timeFrame,
            "generated_message": ad_output,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/")
async def root():
    return {"status": "AOE Motors agentic AI is live"}

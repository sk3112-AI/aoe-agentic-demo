from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate
import datetime
import uvicorn
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# LangChain + OpenAI Setup
llm = OpenAI(temperature=0.7)

prompt_template = PromptTemplate(
    input_variables=["vehicle", "location", "date", "current_vehicle", "time_frame"],
    template=""" 
Generate a persuasive follow-up message for a customer who booked a test drive.

Vehicle: {vehicle}
Location: {location}
Date: {date}
Current Vehicle: {current_vehicle}
Purchase Timeframe: {time_frame}

Tone: Match based on vehicle type (luxury for sedan, rugged for SUV, tech-savvy for electric).
Compare briefly with current vehicle brand if provided.
End with a confident call to action.

Output:
<message>
"""
)

# FastAPI App Setup
app = FastAPI()

# CORS Setup
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

        email_body = f""" 
Hi {payload.fullName},

Thank you for booking your test drive of the AOE {payload.vehicle}. 

{ad_output}

We will be in touch soon to confirm your appointment.

Best regards,  
Team AOE Motors
"""

        send_email(
            to_email=payload.email,
            subject=f"Thank You for Booking Your AOE {payload.vehicle} Test Drive",
            body=email_body
        )

        internal_body = f""" 
New Test Drive Lead:

Name: {payload.fullName}
Email: {payload.email}
Phone: {payload.phone}
Vehicle: {payload.vehicle}
Location: {payload.location}
Date: {payload.date}
Current Vehicle: {payload.currentVehicle}
Purchase Timeframe: {payload.timeFrame}

Generated Message:
{ad_output}
"""

        internal_email = os.getenv("TEAM_EMAIL") or "sales@aoemotors.com"
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
    return {"message": "AOE Agentic AI Server is Live"}

# Run for local testing
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
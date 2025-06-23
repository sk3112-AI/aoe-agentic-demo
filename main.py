
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
    template="""
Generate a short and compelling message for a customer who has booked a test drive.

Vehicle: {vehicle}
Location: {location}
Date: {date}
Current Vehicle: {current_vehicle}
Time Frame to Purchase: {time_frame}

Include a brief persuasive comparison with the current vehicle (if available), highlight top features of the AOE vehicle, and keep it concise.
Do not use phrases like 'ad preview'. Avoid repeating greetings or rebooking prompts.

Format:
<message>
    """
)

# ----------------------
# FastAPI App Setup
# ----------------------
app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your frontend domain
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

        ad_output = llm.invoke(prompt).strip()

        email_body = f"""Hi {payload.fullName},

Thank you for booking a test drive for the AOE {payload.vehicle}.

{ad_output}

Our team will contact you soon to confirm your appointment.

Best regards,  
AOE Motors
"""

        send_email(
            to_email=payload.email,
            subject=f"Thank you for booking your AOE {payload.vehicle} test drive",
            body=email_body
        )

        internal_body = f"""New Test Drive Lead:

Name: {payload.fullName}
Email: {payload.email}
Phone: {payload.phone}
Vehicle: {payload.vehicle}
Location: {payload.location}
Date: {payload.date}
Current Vehicle: {payload.currentVehicle}
Time Frame to Purchase: {payload.timeFrame}

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
            "generated_message": ad_output,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

    except Exception as e:
        return {"error": str(e)}

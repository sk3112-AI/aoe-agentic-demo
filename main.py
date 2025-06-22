
from fastapi import FastAPI
from pydantic import BaseModel
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate
import datetime
import uvicorn
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from fastapi.middleware.cors import CORSMiddleware
# ----------------------
# LangChain + OpenAI Setup
# ----------------------
llm = OpenAI(temperature=0.7)

# ----------------------
# FastAPI App Setup
# ----------------------
app = FastAPI()
origins = [
    "https://aoe-motors.lovable.app",
    "http://localhost:3000",
    "http://127.0.0.1:8000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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
        # Determine persona & intro by vehicle
        vehicle_type = payload.vehicle.lower()

        if "apex" in vehicle_type:
            persona = "luxury sedan buyer looking for comfort, sophistication, and performance"
            intro = f"The AOE Apex is the pinnacle of luxury, blending elegant design with exhilarating performance."
        elif "thunder" in vehicle_type:
            persona = "performance SUV enthusiast who values power, space, and versatility"
            intro = f"The AOE Thunder delivers unmatched power and adaptability—perfect for those who crave both comfort and adventure."
        elif "volt" in vehicle_type:
            persona = "eco-conscious electric vehicle adopter seeking cutting-edge innovation and sustainability"
            intro = f"The AOE Volt is engineered for the future—eco-friendly, tech-packed, and exhilarating to drive."
        else:
            persona = "car enthusiast"
            intro = f"The AOE {payload.vehicle} is built to exceed expectations with design and technology that stands out."

        # LangChain prompt
        prompt = f"""
Act as a copywriter for a car company. Write a high-conversion short paragraph to build excitement for a customer who booked a test drive.
Target: {persona}
Vehicle: {payload.vehicle}
Location: {payload.location}
Date: {payload.date}

Format:
Headline: <headline>
Body: <body>
        """

        ad_output = llm(prompt).strip()

        # Customer email
        customer_email_body = f"""
Hi {payload.fullName},

Thank you for booking a test drive for the AOE {payload.vehicle}!

{intro}

{ad_output}

We’ll contact you shortly to confirm the appointment and share further details.

Warm regards,  
AOE Motors
        """

        # Internal team email
        team_email_body = f"""
New Test Drive Lead:

Name: {payload.fullName}
Email: {payload.email}
Phone: {payload.phone}
Vehicle: {payload.vehicle}
Location: {payload.location}
Date: {payload.date}

Generated Content:
{ad_output}
        """

        # Send both emails
        send_email(
            payload.email,
            subject=f"Thank you for booking your AOE {payload.vehicle} test drive!",
            body=customer_email_body
        )

        internal_team_email = os.getenv("TEAM_EMAIL")
        send_email(
            internal_team_email,
            subject=f"[New Lead] AOE {payload.vehicle}",
            body=team_email_body
        )

        return {
            "customer": payload.fullName,
            "vehicle": payload.vehicle,
            "generated_text": ad_output,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/preview")
async def preview_ui():
    html_content = """
    <html>
        <head><title>AOE Agent Preview</title></head>
        <body style='font-family: Arial;'>
            <h2>AOE Motors - Agentic Ad Generator</h2>
            <p>Submit your test drive form and view results here via /webhook/testdrive</p>
            <p>This is a placeholder UI endpoint. You can extend this to read logs or display ad history.</p>
        </body>
    </html>
    """
    return html_content

# ----------------------
# Run the app (for local testing only)
# ----------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

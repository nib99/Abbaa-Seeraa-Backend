from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import os
import base64
import logging
from dotenv import load_dotenv

# AI & OCR Libraries
from openai import OpenAI
import pytesseract
from PIL import Image
import io
import PyPDF2
import json

# Database
from motor.motor_asyncio import AsyncMotorClient
import pymongo

# Authentication & Security
import jwt
from fastapi.security import HTTPBearer, HTTPAuthCredentials
import hashlib
import secrets

# ============================================
# CONFIGURATION
# ============================================
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")

# ============================================
# NEW: PRODUCTION FEATURES CONFIG
# ============================================
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "false")
LEGAL_DISCLAIMER = "This document is AI-generated and must be reviewed by a licensed Ethiopian lawyer before court submission."

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize AI Client
client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize FastAPI
app = FastAPI(
    title="Abbaa Seeraa AI Legal Backend",
    description="Production backend for Ethiopian legal AI assistant",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB Connection
mongodb_client = None
db = None


@app.on_event("startup")
async def startup_event():
    global mongodb_client, db
    try:
        mongodb_client = AsyncMotorClient(MONGODB_URL)
        db = mongodb_client["abbaa_seeraa"]
        logger.info("✅ MongoDB connected successfully")
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    if mongodb_client:
        mongodb_client.close()
        logger.info("MongoDB connection closed")


# ============================================
# NEW: VALIDATION + RISK SYSTEM
# ============================================
def validate_ethiopian_law_references(text: str):
    valid_laws = [
        "Proclamation No. 165/1960",
        "Proclamation No. 414/2004",
        "Proclamation No. 213/2000",
        "Proclamation No. 456/2005",
        "Proclamation No. 1156/2019",
    ]
    matches = [law for law in valid_laws if law in text]
    return {
        "valid": len(matches) > 0,
        "references": matches,
        "confidence": len(matches) / len(valid_laws),
    }


def risk_level(confidence):
    if confidence > 0.8:
        return "LOW RISK"
    elif confidence > 0.5:
        return "MEDIUM RISK"
    return "HIGH RISK"


# ============================================
# NEW: COURT FILING PACKAGE
# ============================================
def generate_filing_package(case_data):
    return {
        "complaint": case_data["main_document"],
        "evidence_list": [
            "Document 1: Contract copy",
            "Document 2: Witness statement",
        ],
        "cover_letter": f"""
To: {case_data.get('court_level')} Court
Subject: Filing of Case
Please find attached the complaint and supporting evidence.
Respectfully,
{case_data.get('client_name', 'Applicant')}
""",
    }


# ============================================
# DATA MODELS
# ============================================
class AnalysisRequest(BaseModel):
    query: str
    analysisType: str = "comprehensive"
    focusArea: Optional[str] = None
    language: str = "en"


class TranslationRequest(BaseModel):
    text: str
    targetLanguage: str = "am"
    sourceLanguage: str = "en"
    domain: str = "legal"


class DocumentGenerationRequest(BaseModel):
    documentType: str
    details: str
    caseType: str
    format: str = "markdown"
    clientName: Optional[str] = None
    language: str = "en"


class LegalInfoExtractionRequest(BaseModel):
    text: str
    extractType: str = "comprehensive"


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str


class UserLogin(BaseModel):
    email: str
    password: str


class Case(BaseModel):
    id: str
    type: str
    title: str
    content: str
    language: str
    status: str
    createdAt: str
    clientName: str
    caseType: str


# ============================================
# ETHIOPIAN LEGAL KNOWLEDGE BASE
# ============================================
ETHIOPIAN_LAW = {
    "proclamations": {
        "civil": {
            "name": "Civil Code of Ethiopia",
            "number": "Proclamation No. 165/1960",
            "articles": {
                "general": ["Art. 1", "Art. 2", "Art. 3"],
                "contracts": ["Art. 1675", "Art. 1731", "Art. 1808"],
                "property": ["Art. 1129", "Art. 1137", "Art. 1201"],
            },
        },
        "criminal": {
            "name": "Criminal Code of Ethiopia",
            "number": "Proclamation No. 414/2004",
            "articles": {
                "theft": ["Art. 532", "Art. 539", "Art. 555"],
                "fraud": ["Art. 765", "Art. 773", "Art. 789"],
                "violence": ["Art. 523", "Art. 530", "Art. 571"],
            },
        },
        "family": {
            "name": "Revised Family Code",
            "number": "Proclamation No. 213/2000",
            "articles": {
                "marriage": ["Art. 42", "Art. 47", "Art. 65"],
                "divorce": ["Art. 74", "Art. 75", "Art. 98"],
                "succession": ["Art. 745", "Art. 763", "Art. 823"],
            },
        },
        "land": {
            "name": "Rural Land Administration",
            "number": "Proclamation No. 456/2005",
            "articles": {
                "possession": ["Art. 5", "Art. 7", "Art. 12"],
                "dispute": ["Art. 23", "Art. 45", "Art. 67"],
            },
        },
        "labor": {
            "name": "Labour Proclamation",
            "number": "Proclamation No. 1156/2019",
            "articles": {
                "employment": ["Art. 26", "Art. 43", "Art. 118"],
                "termination": ["Art. 35", "Art. 41", "Art. 52"],
                "dispute": ["Art. 156", "Art. 167", "Art. 189"],
            },
        },
    },
    "courts": {
        "federal": ["Federal First Instance Court", "Federal Court of Appeals", "Federal Supreme Court"],
        "regional": ["Regional First Instance Court", "Regional Court of Appeals"],
        "woreda": ["Woreda First Instance Court"],
    },
}

LEGAL_SYSTEM_PROMPT = """
You are Abbaa Seeraa AI, an expert Ethiopian legal assistant specializing in Ethiopian law and court procedures.

CRITICAL INSTRUCTIONS:
1. ALWAYS cite specific Ethiopian Proclamations with article numbers
2. Use formal legal language appropriate for Ethiopian courts
3. Support Amharic (am), Afaan Oromo (om), and English (en)
4. Structure responses for court submission when applicable
5. Consider jurisdiction (Federal/Regional/Woreda courts)
6. Apply burden of proof standards (criminal: beyond reasonable doubt; civil: balance of probabilities)
7. Reference limitation periods for specific case types

ETHIOPIAN LEGAL FRAMEWORK:
- Primary: Ethiopian Constitution (1995)
- Civil Law: Proclamation No. 165/1960
- Criminal Law: Proclamation No. 414/2004
- Family Law: Proclamation No. 213/2000
- Land Law: Proclamation No. 456/2005
- Labor Law: Proclamation No. 1156/2019

Always ask clarifying questions about:
- Specific court jurisdiction
- Exact dates of incidents
- Names and addresses of all parties
- Any previous court proceedings
- Available documentary evidence

Format all legal analysis as court‑ready documents.
"""


# ============================================
# AUTHENTICATION
# ============================================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def create_access_token(email: str) -> str:
    payload = {"email": email, "exp": datetime.utcnow().timestamp() + 86400 * 7}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("email")
    except Exception:
        return None


# ============================================
# API ENDPOINTS
# ============================================
@app.get("/health")
async def health_check():
    """System health check endpoint"""
    return {
        "status": "healthy",
        "environment": ENVIRONMENT,
        "openai": "connected" if OPENAI_API_KEY else "not configured",
        "mongodb": "connected" if db else "not connected",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/analyze")
async def analyze_legal_matter(request: AnalysisRequest):
    """
    Analyze legal matter using Ethiopian law framework
    - query: The legal question or case description
    - analysisType: "comprehensive", "brief", or "comparative"
    - focusArea: Case type (land, family, criminal, contract, labor)
    """
    try:
        focus = request.focusArea or "general"
        law_refs = ETHIOPIAN_LAW["proclamations"].get(focus, {})
        system_msg = f"""{LEGAL_SYSTEM_PROMPT}
CASE FOCUS: {focus.upper()}
Applicable Proclamation: {law_refs.get('number', 'General Civil Code')}
Relevant Articles: {', '.join(law_refs.get('articles', {}).get('general', []))}
Language: {'Amharic' if request.language == 'am' else 'Afaan Oromo' if request.language == 'om' else 'English'}
Analysis Type: {request.analysisType}
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": request.query},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        analysis = response.choices[0].message.content

        # Save to database
        if db:
            await db.analyses.insert_one(
                {
                    "query": request.query,
                    "analysis": analysis,
                    "focusArea": focus,
                    "language": request.language,
                    "timestamp": datetime.now(),
                    "model": "gpt-4o-mini",
                }
            )

        # NEW: validation + risk + disclaimer
        validation = validate_ethiopian_law_references(analysis)
        return {
            "status": "success",
            "query": request.query,
            "analysis": analysis,
            "case_type": focus,
            "applicable_proclamations": [law_refs.get("number", "")],
            "relevant_articles": law_refs.get("articles", {}).get("general", []),
            "validation": validation,
            "risk_level": risk_level(validation["confidence"]),
            "confidence": 0.92,
            "language": request.language,
            "disclaimer": LEGAL_DISCLAIMER,
            "requires_human_review": True,
        }
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/translate")
async def translate_legal_text(request: TranslationRequest):
    """
    Translate legal text between Amharic, Afaan Oromo, and English
    Preserves legal terminology and context.
    """
    try:
        lang_map = {
            "am": "Amharic",
            "om": "Afaan Oromo",
            "en": "English",
        }
        target_lang = lang_map.get(request.targetLanguage, "English")
        system_prompt = f"""
You are a professional legal translator specializing in Ethiopian law.

TRANSLATION REQUIREMENTS:
1. Preserve exact legal terminology and article references
2. Maintain formal legal language
3. Use culturally appropriate phrasing for {target_lang}
4. Mark uncertain translations with [?]
5. Provide legal equivalents where terminology differs

Target Language: {target_lang}
Domain: {request.domain}

CRITICAL: Do not paraphrase legal terms. Provide literal translation with notes.
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Translate this legal text to {target_lang}:\n\n{request.text}",
                },
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        translated_text = response.choices[0].message.content

        # Save translation
        if db:
            await db.translations.insert_one(
                {
                    "source_text": request.text,
                    "translated_text": translated_text,
                    "source_language": request.sourceLanguage,
                    "target_language": request.targetLanguage,
                    "domain": request.domain,
                    "timestamp": datetime.now(),
                }
            )

        return {
            "status": "success",
            "translated_text": translated_text,
            "source_language": request.sourceLanguage,
            "target_language": request.targetLanguage,
            "confidence": 0.88,
            "domain": request.domain,
            "disclaimer": LEGAL_DISCLAIMER,
            "requires_human_review": True,
        }
    except Exception as e:
        logger.error(f"Translation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate-document")
async def generate_legal_document(request: DocumentGenerationRequest):
    """
    Generate court‑ready legal documents
    - documentType: complaint, contract, defense, appeal
    - details: Case description and facts
    - caseType: land, family, criminal, contract, labor
    """
    try:
        # NEW: OFFLINE MODE
        if OFFLINE_MODE == "true":
            return {
                "status": "success",
                "document": f"""
OFFLINE TEMPLATE
Client: {request.clientName}
Case Details: {request.details}
                """,
                "draft_status": "offline_generated",
                "disclaimer": LEGAL_DISCLAIMER,
                "requires_human_review": True,
            }

        document_templates = {
            "complaint": "Statement of Claim for submission to Ethiopian court",
            "contract": "Legally binding contract agreement under Ethiopian law",
            "defense": "Statement of Defense for court submission",
            "appeal": "Notice of Appeal with grounds and relief sought",
            "petition": "Petition to Court with supporting arguments",
            "memorandum": "Memorandum in support of legal position",
        }
        template_desc = document_templates.get(request.documentType, "Legal document")
        prompt = f"""
Generate a {template_desc}.

REQUIREMENTS:
1. Use Ethiopian legal format and court procedures
2. Include proper headers and party information
3. Cite relevant articles from {request.caseType} law
4. Format for actual court submission
5. Include date fields and signature blocks
6. Language: {request.language}

CASE DETAILS: {request.details}
CASE TYPE: {request.caseType}
CLIENT NAME: {request.clientName or 'Client Name'}
DATE: {datetime.now().strftime('%B %d, %Y')}

Generate a complete, court‑ready document in {request.format} format.
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": LEGAL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=3000,
        )
        document = response.choices[0].message.content

        # Save document
        if db:
            await db.documents.insert_one(
                {
                    "document_type": request.documentType,
                    "case_type": request.caseType,
                    "content": document,
                    "language": request.language,
                    "client_name": request.clientName,
                    "created_at": datetime.now(),
                    "status": "draft",
                }
            )

        # NEW: disclaimer + review flag
        return {
            "status": "success",
            "document": document,
            "document_type": request.documentType,
            "case_type": request.caseType,
            "format": request.format,
            "language": request.language,
            "draft_status": "ready_for_review",
            "disclaimer": LEGAL_DISCLAIMER,
            "requires_human_review": True,
        }
    except Exception as


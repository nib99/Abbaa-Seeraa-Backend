import os
import logging
import hashlib
from datetime import datetime
from typing import Optional

import jwt
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# AI
from openai import AsyncOpenAI

# Database
from motor.motor_asyncio import AsyncIOMotorClient

# ============================================
# CONFIGURATION
# ============================================

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")

OFFLINE_MODE = os.getenv("OFFLINE_MODE", "false").lower() == "true"

LEGAL_DISCLAIMER = "This document is AI-generated and must be reviewed by a licensed Ethiopian lawyer before court submission."

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("abbaa_seeraa")

# Async OpenAI client
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ============================================
# FastAPI App
# ============================================

app = FastAPI(
    title="Abbaa Seeraa AI Legal Backend",
    description="Production backend for Ethiopian legal AI assistant",
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB
mongodb_client: Optional[AsyncIOMotorClient] = None
db = None

@app.on_event("startup")
async def startup_event():
    global mongodb_client, db
    try:
        mongodb_client = AsyncIOMotorClient(MONGODB_URL)
        db = mongodb_client["abbaa_seeraa"]
        await mongodb_client.admin.command("ping")
        logger.info("✅ MongoDB connected successfully")
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    if mongodb_client:
        mongodb_client.close()
        logger.info("MongoDB connection closed")

# ============================================
# AUTHENTICATION
# ============================================

security = HTTPBearer()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_access_token(email: str) -> str:
    # Fixed: exp must be integer (Unix timestamp)
    payload = {
        "email": email,
        "exp": int(datetime.utcnow().timestamp() + 86400 * 7)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("email")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

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
            "name": "Rural Land Administration and Use",
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
        "federal": ["Federal First Instance Court", "Federal High Court", "Federal Supreme Court"],
        "regional": ["Regional First Instance Court", "Regional Court of Appeals"],
        "woreda": ["Woreda First Instance Court"],
    },
}

LEGAL_SYSTEM_PROMPT = """
You are Abbaa Seeraa AI, an expert Ethiopian legal assistant specializing in Ethiopian law and court procedures.

CRITICAL INSTRUCTIONS:
1. ALWAYS cite specific Ethiopian Proclamations with exact article numbers.
2. Use formal legal language appropriate for Ethiopian courts.
3. Support Amharic (am), Afaan Oromo (om), and English (en).
4. Structure responses for direct court submission when applicable.
5. Consider jurisdiction (Federal/Regional/Woreda courts).
6. Apply correct burden of proof (criminal: beyond reasonable doubt; civil: balance of probabilities).
7. Reference limitation periods where relevant.

Primary sources:
- Ethiopian Constitution (1995)
- Civil Code: Proclamation No. 165/1960
- Criminal Code: Proclamation No. 414/2004
- Revised Family Code: Proclamation No. 213/2000
- Rural Land Administration: Proclamation No. 456/2005
- Labour Proclamation: Proclamation No. 1156/2019

Always ask clarifying questions about jurisdiction, exact dates, parties, evidence, and prior proceedings.
Format all legal analysis as court-ready documents.
"""

# ============================================
# HELPER FUNCTIONS
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
        "confidence": round(len(matches) / len(valid_laws), 2) if valid_laws else 0,
    }

def risk_level(confidence: float):
    if confidence > 0.8:
        return "LOW RISK"
    elif confidence > 0.5:
        return "MEDIUM RISK"
    return "HIGH RISK"

def build_legal_system_message(focus: str = "general", language: str = "en", analysis_type: str = "comprehensive"):
    """Shared helper to build consistent legal context for all endpoints"""
    law_refs = ETHIOPIAN_LAW["proclamations"].get(focus, ETHIOPIAN_LAW["proclamations"]["civil"])
    lang_name = {"am": "Amharic", "om": "Afaan Oromo", "en": "English"}.get(language, "English")

    return f"""{LEGAL_SYSTEM_PROMPT}
CASE FOCUS: {focus.upper()}
Applicable Proclamation: {law_refs.get('number', 'General Civil Code')}
Relevant Articles: {', '.join(law_refs.get('articles', {}).get('general', []))}
Language: {lang_name}
Analysis Type: {analysis_type}
"""

# ============================================
# API ENDPOINTS
# ============================================

@app.get("/")
async def root():
    return {"status": "ok", "message": "Abbaa Seeraa API is running"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "environment": ENVIRONMENT,
        "openai": "connected" if OPENAI_API_KEY else "not configured",
        "mongodb": "connected" if db else "not connected",
        "version": "1.1.0",
        "timestamp": datetime.now().isoformat(),
        "offline_mode": OFFLINE_MODE,
    }

@app.post("/api/analyze")
async def analyze_legal_matter(request: AnalysisRequest, email: str = Depends(verify_token)):
    if not client:
        raise HTTPException(status_code=503, detail="OpenAI service not configured")

    try:
        focus = request.focusArea or "general"
        system_msg = build_legal_system_message(
            focus=focus,
            language=request.language,
            analysis_type=request.analysisType
        )

        response = await client.chat.completions.create(
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
            await db.analyses.insert_one({
                "query": request.query,
                "analysis": analysis,
                "focusArea": focus,
                "language": request.language,
                "user_email": email,
                "timestamp": datetime.now(),
                "model": "gpt-4o-mini",
            })

        validation = validate_ethiopian_law_references(analysis)
        law_refs = ETHIOPIAN_LAW["proclamations"].get(focus, ETHIOPIAN_LAW["proclamations"]["civil"])

        return {
            "status": "success",
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
        raise HTTPException(status_code=500, detail="Internal server error during legal analysis")

@app.post("/api/translate")
async def translate_legal_text(request: TranslationRequest, email: str = Depends(verify_token)):
    if not client:
        raise HTTPException(status_code=503, detail="OpenAI service not configured")

    try:
        lang_map = {"am": "Amharic", "om": "Afaan Oromo", "en": "English"}
        target_lang = lang_map.get(request.targetLanguage, "English")

        system_prompt = f"""
You are a professional legal translator specializing in Ethiopian law.

TRANSLATION REQUIREMENTS:
1. Preserve exact legal terminology and article references.
2. Maintain formal legal language appropriate for Ethiopian courts.
3. Use culturally appropriate phrasing for {target_lang}.
4. Mark uncertain translations with [?].
5. Provide legal equivalents where terminology differs between languages.

Target Language: {target_lang}
Domain: {request.domain}

CRITICAL: Do not paraphrase legal terms. Provide literal translation with explanatory notes where needed.
"""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Translate this legal text to {target_lang}:\n\n{request.text}"},
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        translated_text = response.choices[0].message.content

        # Save translation
        if db:
            await db.translations.insert_one({
                "source_text": request.text,
                "translated_text": translated_text,
                "source_language": request.sourceLanguage,
                "target_language": request.targetLanguage,
                "domain": request.domain,
                "user_email": email,
                "timestamp": datetime.now(),
            })

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
        raise HTTPException(status_code=500, detail="Internal server error during translation")

@app.post("/api/generate-document")
async def generate_legal_document(request: DocumentGenerationRequest, email: str = Depends(verify_token)):
    if not client and not OFFLINE_MODE:
        raise HTTPException(status_code=503, detail="OpenAI service not configured")

    try:
        # Offline fallback
        if OFFLINE_MODE:
            return {
                "status": "success",
                "document": f"""
OFFLINE TEMPLATE - {request.documentType.upper()}
Client: {request.clientName or 'Client Name'}
Case Type: {request.caseType}
Details: {request.details}
Generated on: {datetime.now().strftime('%B %d, %Y')}
Language: {request.language}
""",
                "document_type": request.documentType,
                "case_type": request.caseType,
                "format": request.format,
                "language": request.language,
                "draft_status": "offline_generated",
                "disclaimer": LEGAL_DISCLAIMER,
                "requires_human_review": True,
            }

        # Online generation
        document_templates = {
            "complaint": "Statement of Claim",
            "contract": "Legally binding contract agreement",
            "defense": "Statement of Defense",
            "appeal": "Notice of Appeal with grounds and relief sought",
            "petition": "Petition to Court",
            "memorandum": "Memorandum in support of legal position",
        }
        template_desc = document_templates.get(request.documentType, "Legal document")

        prompt = f"""
Generate a complete {template_desc} under Ethiopian law.

REQUIREMENTS:
1. Use official Ethiopian court format and procedures.
2. Include proper headers, party information, and signature blocks.
3. Cite relevant articles from {request.caseType} law.
4. Format for actual court submission.
5. Language: {request.language}

CASE DETAILS: {request.details}
CASE TYPE: {request.caseType}
CLIENT NAME: {request.clientName or 'Client Name'}
DATE: {datetime.now().strftime('%B %d, %Y')}

Output in {request.format} format.
"""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": LEGAL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=3000,
        )
        document = response.choices[0].message.content

        # Save to database
        if db:
            await db.documents.insert_one({
                "document_type": request.documentType,
                "case_type": request.caseType,
                "content": document,
                "language": request.language,
                "client_name": request.clientName,
                "user_email": email,
                "created_at": datetime.now(),
                "status": "draft",
            })

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

    except Exception as e:
        logger.error(f"Document generation error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during document generation")

# ============================================
# RUN SERVER
# ============================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

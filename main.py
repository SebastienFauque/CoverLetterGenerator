from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from typing import Optional
import os
import re
from pathlib import Path
import json
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from pydantic_ai import Agent
from dotenv import load_dotenv
import PyPDF2
import io

load_dotenv()

app = FastAPI(title="Cover Letter Generator", description="Generate personalized cover letters from job descriptions and resumes")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle JSON validation errors with helpful messages.
    
    Args:
        request (Request): The request that caused the error.
        exc (RequestValidationError): The validation exception.
        
    Returns:
        JSONResponse: User-friendly error message.
    """
    return JSONResponse(
        status_code=400,
        content={
            "error": "Invalid input format",
            "message": "Please ensure your job description text doesn't contain special control characters. Try copying and pasting into a plain text editor first, then copy from there.",
            "details": str(exc.errors())
        }
    )

class ResumeData(BaseModel):
    content: str

class SaveLocation(BaseModel):
    directory_path: str

class JobDescription(BaseModel):
    content: str
    
    @field_validator('content')
    @classmethod
    def sanitize_content(cls, v: str) -> str:
        """Remove or replace problematic control characters from job description text.
        
        Args:
            v (str): Input job description text.
            
        Returns:
            str: Sanitized text safe for JSON processing.
        """
        import unicodedata
        
        # Remove control characters except newlines, tabs, and carriage returns
        sanitized = ''.join(char for char in v if unicodedata.category(char)[0] != 'C' or char in '\n\r\t')
        
        # Replace problematic characters
        sanitized = sanitized.replace('\x00', '')  # Remove null bytes
        sanitized = sanitized.replace('\b', '')    # Remove backspace
        sanitized = sanitized.replace('\f', '')    # Remove form feed
        sanitized = sanitized.replace('\v', '')    # Remove vertical tab
        
        return sanitized

class AppState:
    def __init__(self):
        self.data_file = "app_data.json"
        self.resume: Optional[str] = None
        self.save_directory: Optional[str] = None
        self.load_data()
    
    def load_data(self):
        """Load resume and save directory from persistent storage.
        
        Loads data from JSON file if it exists, otherwise uses defaults.
        """
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.resume = data.get('resume')
                    self.save_directory = data.get('save_directory')
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load app data: {e}")
    
    def save_data(self):
        """Save current resume and save directory to persistent storage.
        
        Saves data to JSON file for persistence between sessions.
        """
        try:
            data = {
                'resume': self.resume,
                'save_directory': self.save_directory
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"Warning: Could not save app data: {e}")

app_state = AppState()

agent = Agent(
    'openai:gpt-4',
    system_prompt="""You are a professional cover letter writer. Given a resume and job description, 
    create a compelling, personalized cover letter that:
    1. Highlights relevant experience from the resume
    2. Addresses key requirements from the job posting
    3. Shows enthusiasm for the role and company
    4. Is professional yet engaging
    5. Is 3-4 paragraphs long
    
    Return only the cover letter text without any additional formatting or metadata.
    Also extract and return the company name, job title, and job ID (if available) in a JSON format at the end.
    
    Format your response as:
    [COVER_LETTER_TEXT]
    
    JSON_DATA:
    {"company_name": "Company Name", "job_title": "Job Title", "job_id": "ID or null"}
    """
)

@app.post("/resume")
async def set_resume(resume_data: ResumeData):
    """Set resume content as string.
    
    Args:
        resume_data (ResumeData): Resume content to store.
        
    Returns:
        dict: Success message and content length.
    """
    app_state.resume = resume_data.content
    app_state.save_data()
    return {"message": "Resume saved successfully", "length": len(resume_data.content)}

@app.post("/resume-file")
async def set_resume_file(file: UploadFile = File(...)):
    """Set resume content from uploaded file.
    
    Args:
        file (UploadFile): Text, markdown, or PDF file containing resume content.
        
    Returns:
        dict: Success message and content length.
        
    Raises:
        HTTPException: If file format is not supported or processing fails.
    """
    if not file.filename.endswith(('.txt', '.md', '.pdf')):
        raise HTTPException(status_code=400, detail="Only .txt, .md, and .pdf files are supported")
    
    try:
        content = await file.read()
        
        if file.filename.endswith('.pdf'):
            app_state.resume = extract_text_from_pdf(content)
        else:
            app_state.resume = content.decode('utf-8')
        
        app_state.save_data()
        return {"message": f"Resume file '{file.filename}' processed successfully", "length": len(app_state.resume)}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

@app.post("/save-location")
async def set_save_location(location: SaveLocation):
    """Set directory where cover letters will be saved.
    
    Args:
        location (SaveLocation): Directory path for saving PDFs.
        
    Returns:
        dict: Success message with directory path.
        
    Raises:
        HTTPException: If directory doesn't exist or is not a directory.
    """
    path = Path(location.directory_path)
    if not path.exists():
        raise HTTPException(status_code=400, detail="Directory does not exist")
    if not path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    
    app_state.save_directory = location.directory_path
    app_state.save_data()
    return {"message": f"Save location set to: {location.directory_path}"}

def generate_filename(company_name: str, job_title: str, job_id: Optional[str] = None) -> str:
    """Generate filename based on company, job title, and optional job ID.
    
    Args:
        company_name (str): Name of the company.
        job_title (str): Job title for the position.
        job_id (Optional[str]): Optional job ID or reference number.
        
    Returns:
        str: Generated filename in format 'company_jobtitle_jobid.pdf'.
    """
    company_clean = re.sub(r'[^\w\s-]', '', company_name).strip()
    company_clean = re.sub(r'[-\s]+', '_', company_clean)
    
    job_title_words = re.sub(r'[^\w\s-]', '', job_title).split()
    job_title_abbrev = ''.join([word[0].upper() for word in job_title_words if word])
    
    filename_parts = [company_clean, job_title_abbrev]
    if job_id:
        job_id_clean = re.sub(r'[^\w-]', '', str(job_id))
        filename_parts.append(job_id_clean)
    
    return '_'.join(filename_parts) + '.pdf'

def create_pdf(content: str, filepath: str):
    """Create PDF from cover letter content.
    
    Args:
        content (str): Cover letter text content.
        filepath (str): Full path where PDF will be saved.
    """
    doc = SimpleDocTemplate(filepath, pagesize=letter)
    styles = getSampleStyleSheet()
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
        spaceAfter=12
    )
    
    story = []
    paragraphs = content.split('\n\n')
    
    for para in paragraphs:
        if para.strip():
            story.append(Paragraph(para.strip(), normal_style))
            story.append(Spacer(1, 12))
    
    doc.build(story)

def extract_text_from_pdf(pdf_content: bytes) -> str:
    """Extract text content from PDF file.
    
    Args:
        pdf_content (bytes): PDF file content as bytes.
        
    Returns:
        str: Extracted text content from the PDF.
        
    Raises:
        Exception: If PDF processing fails.
    """
    try:
        pdf_stream = io.BytesIO(pdf_content)
        pdf_reader = PyPDF2.PdfReader(pdf_stream)
        
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        
        return text.strip()
    except Exception as e:
        raise Exception(f"Failed to extract text from PDF: {str(e)}")

@app.post("/generate-cover-letter-text")
async def generate_cover_letter_text(job_description: str):
    """Generate cover letter from job description text string.
    
    Args:
        job_description (str): Job description text as a simple string parameter.
        
    Returns:
        dict: Success message with filename, filepath, and extracted job info.
        
    Raises:
        HTTPException: If resume or save location not set, or generation fails.
    """
    if not app_state.resume:
        raise HTTPException(status_code=400, detail="Resume not set. Use /resume or /resume-file endpoint first.")
    
    if not app_state.save_directory:
        raise HTTPException(status_code=400, detail="Save location not set. Use /save-location endpoint first.")
    
    if not job_description or not job_description.strip():
        raise HTTPException(status_code=400, detail="Job description cannot be empty.")
    
    try:
        # Sanitize the text
        import unicodedata
        sanitized = ''.join(char for char in job_description if unicodedata.category(char)[0] != 'C' or char in '\n\r\t')
        sanitized = sanitized.replace('\x00', '').replace('\b', '').replace('\f', '').replace('\v', '')
        
        return await _process_cover_letter(sanitized)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating cover letter: {str(e)}")

async def _process_cover_letter(job_description_text: str):
    """Process cover letter generation with job description text.
    
    Args:
        job_description_text (str): Sanitized job description text.
        
    Returns:
        dict: Success message with filename, filepath, and extracted job info.
    """
    prompt = f"""
    Resume:
    {app_state.resume}
    
    Job Description:
    {job_description_text}
    
    Create a personalized cover letter for this job application.
    """
    
    result = await agent.run(prompt)
    response_text = str(result.data)
    
    if "JSON_DATA:" in response_text:
        cover_letter_text = response_text.split("JSON_DATA:")[0].strip()
        json_part = response_text.split("JSON_DATA:")[1].strip()
        try:
            job_info = json.loads(json_part)
            company_name = job_info.get("company_name", "Unknown_Company")
            job_title = job_info.get("job_title", "Position")
            job_id = job_info.get("job_id")
        except json.JSONDecodeError:
            company_name = "Unknown_Company"
            job_title = "Position"
            job_id = None
    else:
        cover_letter_text = response_text
        company_name = "Unknown_Company"
        job_title = "Position"
        job_id = None
    
    filename = generate_filename(company_name, job_title, job_id)
    filepath = os.path.join(app_state.save_directory, filename)
    
    create_pdf(cover_letter_text, filepath)
    
    return {
        "message": "Cover letter generated and saved successfully",
        "filename": filename,
        "filepath": filepath,
        "company": company_name,
        "job_title": job_title,
        "job_id": job_id
    }

@app.post("/generate-cover-letter")
async def generate_cover_letter(job_desc: JobDescription):
    """Generate cover letter from job description using stored resume and save to specified location.
    
    Args:
        job_desc (JobDescription): Job description content.
        
    Returns:
        dict: Success message with filename, filepath, and extracted job info.
        
    Raises:
        HTTPException: If resume or save location not set, or generation fails.
    """
    if not app_state.resume:
        raise HTTPException(status_code=400, detail="Resume not set. Use /resume or /resume-file endpoint first.")
    
    if not app_state.save_directory:
        raise HTTPException(status_code=400, detail="Save location not set. Use /save-location endpoint first.")
    
    try:
        return await _process_cover_letter(job_desc.content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating cover letter: {str(e)}")

@app.get("/status")
async def get_status():
    """Get current application status.
    
    Returns:
        dict: Status information including resume and save directory state.
    """
    return {
        "resume_set": app_state.resume is not None,
        "resume_length": len(app_state.resume) if app_state.resume else 0,
        "save_directory": app_state.save_directory
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
# Cover Letter Generator

A FastAPI application that generates personalized cover letters using PydanticAI and OpenAI GPT-4.

## Features

- Accept resume as text or file upload
- Set custom save directory for generated PDFs
- Generate cover letters from job descriptions using LLM
- Automatic PDF generation with smart filename formatting
- RESTful API endpoints

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create `.env` file with your OpenAI API key:
```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

3. Run the application:
```bash
python main.py
```

The API will be available at `http://localhost:8000`

## API Endpoints

### 1. Set Resume (Text)
```
POST /resume
Content-Type: application/json

{
  "content": "Your resume text here..."
}
```

### 2. Set Resume (File Upload)
```
POST /resume-file
Content-Type: multipart/form-data

file: [.txt or .md file]
```

### 3. Set Save Location
```
POST /save-location
Content-Type: application/json

{
  "directory_path": "/path/to/save/directory"
}
```

### 4. Generate Cover Letter
```
POST /generate-cover-letter
Content-Type: application/json

{
  "content": "Job description text here..."
}
```

### 5. Check Status
```
GET /status
```

## Filename Format

Generated PDFs are saved with the format:
`[company_name]_[job_title_abbreviation]_[job_id].pdf`

Example: `Google_SWE_12345.pdf`

## Interactive API Documentation

Visit `http://localhost:8000/docs` for Swagger UI documentation.
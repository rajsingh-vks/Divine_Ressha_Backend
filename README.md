# Divine Reesha Backend

Separate FastAPI backend API connected to MongoDB.

## Setup

1. Create and activate a virtual environment:
   ```bash
   cd /Applications/Divine-Reesha/backend
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure MongoDB:
   ```bash
   cp .env.example .env
   ```

   Update `MONGODB_URI` if your MongoDB instance is not running locally.

4. Run the API:
   ```bash
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

## URLs

- API root: `http://127.0.0.1:8000/`
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- API health: `http://127.0.0.1:8000/health`
- MongoDB health: `http://127.0.0.1:8000/health/db`

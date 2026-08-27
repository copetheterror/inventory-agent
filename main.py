import json
import os
import sqlite3
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
from pydantic import BaseModel
from fastapi.responses import FileResponse

DB_FILE = "inventory.db"

# --- 1. Database Initialization ---
def init_db():
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print(f"Successfully reset database: {DB_FILE}")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            price REAL,
            stock INTEGER,
            reorder_qty INTEGER,
            over_stock_qty INTEGER
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO products (name, category, price, stock, reorder_qty, over_stock_qty)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            ("Wireless Mouse", "Electronics", 29.99, 150, 100, 200),
            ("Mechanical Keyboard", "Electronics", 89.99, 45, 40, 60),
            ("Ergonomic Chair", "Furniture", 199.50, 12, 8, 20),
            ("Coffee Mug", "Kitchen", 12.00, 80, 30, 90)
        ])
        conn.commit()
    conn.close()

# --- 2. Database Tool ---
def query_database(sql_query: str) -> str:
    """Executes a read-only SQL query against 'inventory.db' and returns results in JSON."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(sql_query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        return json.dumps([dict(zip(columns, row)) for row in rows])
    except Exception as e:
        return json.dumps({"error": str(e)})

# --- 3. Agent System Prompt ---
SYSTEM_INSTRUCTION = """
You are an intelligent inventory assistant.
You have access to a local SQLite database named 'inventory.db'.
Table schema: products(id INTEGER, name TEXT, category TEXT, price REAL, stock INTEGER, reorder_qty INTEGER, over_stock_qty INTEGER).
Always query the database using the provided tool before answering questions about inventory, stock, or pricing.
"""

# Lifecycle context to initialize database on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

# Enable CORS to allow browser requests from external frontend web pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Gemini Client (Use environment variables in production)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
#client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))

class QueryRequest(BaseModel):
    prompt: str

# Add this root endpoint:
@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

# --- 4. HTTP API Endpoint ---
@app.post("/api/chat")
async def chat_with_agent(request: QueryRequest):
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=request.prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                tools=[query_database]
            )
        )
        return {"response": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
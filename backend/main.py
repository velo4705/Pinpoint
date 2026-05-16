from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from app.ai_engine import get_engine
import io
import datetime

app = FastAPI(title="Pinpoint AI Engine")

# Discovery Vault (History Storage)
discovery_vault = []

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    try:
        get_engine()
    except Exception as e:
        print(f"Error loading AI engine: {e}")

@app.get("/")
async def root():
    return {"status": "online", "model": "StreetCLIP-V4"}

@app.get("/history")
async def get_history():
    return discovery_vault[-10:] # Return the last 10 discoveries

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form

@app.post("/scan")
async def scan_image(file: UploadFile = File(...), mode: str = Form("real-world"), game: str = Form(None)):
    try:
        contents = await file.read()
        engine = get_engine()
        
        if mode == "real-world":
            result = engine.scan_real_world(contents)
        else:
            result = engine.scan_game(contents, game or "Generic")
            
        if "error" not in result:
            # Add to Discovery Vault
            entry = {
                "id": len(discovery_vault) + 1,
                "timestamp": datetime.datetime.now().isoformat(),
                **result
            }
            discovery_vault.append(entry)
            
        return result
            
    except Exception as e:
        print(f"Scan error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

"""Entry point: python -m kronos_service"""
import uvicorn
import os

port = int(os.getenv("KRONOS_PORT", "8777"))
uvicorn.run("kronos_service.server:app", host="0.0.0.0", port=port)

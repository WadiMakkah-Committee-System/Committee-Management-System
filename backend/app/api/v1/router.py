"""
الهدف:
تجميع كل راوترات النسخة v1 من الـ API في راوتر واحد يُستورَد في main.py.
"""

from fastapi import APIRouter

from app.api.v1 import auth, departments, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(departments.router)

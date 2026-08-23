"""
الهدف:
تجميع كل راوترات النسخة v1 من الـ API في راوتر واحد يُستورَد في main.py.
"""

from fastapi import APIRouter

from app.api.v1 import audit_logs, auth, departments, roles, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(departments.router)
api_router.include_router(roles.router)
api_router.include_router(roles.permissions_router)
api_router.include_router(audit_logs.router)

from fastapi import APIRouter, Body
from app.services import settings_service as svc

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/business-day")
def get_day():
    return svc.get_day()


@router.put("/business-day")
def set_day(body: dict = Body(...)):
    return svc.set_day(body)


@router.get("/cutoff")
def get_cutoff():
    return svc.get_cutoff()


@router.put("/cutoff")
def set_cutoff(body: dict = Body(...)):
    return svc.set_cutoff(body)

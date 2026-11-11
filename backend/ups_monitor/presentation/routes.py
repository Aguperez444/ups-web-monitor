from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AwareDatetime

from ..application.monitor import InvalidHistoryRange, Monitor
from ..domain.ports import SourceUnavailable
from .schemas import CurrentResponse, ErrorResponse, MetricsResponse, SummaryResponse, TelemetryResponse


router = APIRouter()


def get_monitor(request: Request) -> Monitor:
    return request.app.state.monitor


MonitorDependency = Annotated[Monitor, Depends(get_monitor)]


@router.get("/api/ups/current", tags=["Monitoreo"], responses={503: {"model": ErrorResponse}})
def current(request: Request, response: Response, monitor: MonitorDependency) -> CurrentResponse:
    try:
        reading = monitor.current()
    except SourceUnavailable as error:
        raise HTTPException(503, str(error), headers={"Cache-Control": "no-store"}) from error
    response.headers["Cache-Control"] = "no-store"
    return CurrentResponse.from_sample(
        reading.sample,
        ups_name=request.app.state.ups_name,
        manufacturer=reading.manufacturer,
        model=reading.model,
        charger=reading.charger,
    )


@router.get("/api/metrics", tags=["Monitoreo"])
def metrics(
    response: Response,
    monitor: MonitorDependency,
    start: Annotated[datetime, AwareDatetime] | None = None,
    end: Annotated[datetime, AwareDatetime] | None = None,
    window_minutes: Annotated[int | None, Query(ge=1, le=525600)] = None,
    max_points: Annotated[int, Query(ge=3, le=5000)] = 600,
) -> MetricsResponse:
    try:
        result = monitor.history(start, end, max_points, window_minutes=window_minutes)
    except InvalidHistoryRange as error:
        raise HTTPException(422, str(error)) from error
    response.headers["Cache-Control"] = "no-store"
    return MetricsResponse.from_result(result)


@router.get("/ups/raw", tags=["Compatibilidad"])
def raw(monitor: MonitorDependency) -> dict[str, str]:
    try:
        return monitor.read().raw
    except SourceUnavailable as error:
        raise HTTPException(500, str(error)) from error


@router.get("/ups/summary", tags=["Compatibilidad"])
def summary(monitor: MonitorDependency) -> SummaryResponse:
    try:
        reading = monitor.read()
    except SourceUnavailable as error:
        raise HTTPException(500, str(error)) from error
    values = TelemetryResponse.model_validate(reading.sample.telemetry).model_dump()
    return SummaryResponse(**values, raw=reading.raw)


@router.get("/saludo", tags=["Compatibilidad"])
def greeting() -> dict[str, str]:
    return {"chao": "mundo"}

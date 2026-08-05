"""
models.py — Esquemas Pydantic del módulo Jornaleros.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

AREAS_VALIDAS = ("TRANSPORTE", "DESPACHO")


class JornaleroBase(BaseModel):
    fecha_inicial: datetime = Field(..., description="Fecha de inicio del período")
    fecha_final: datetime = Field(..., description="Fecha de fin del período")
    tipo_trabajador: str = Field("JORNALERO", max_length=20)
    cd: str = Field(..., min_length=1, max_length=50, description="Ciudad: COCHABAMBA, LA PAZ, SANTA CRUZ")
    unidad: str = Field("", max_length=100, description="Ej: DISTRIBUCION REGIONAL CBBA")
    area: str = Field("DESPACHO", max_length=20, description="TRANSPORTE o DESPACHO")
    cantidad_jornaleros: float = Field(0.0, ge=0.0)
    horas_trabajadas: float = Field(0.0, ge=0.0)
    dias_trabajados_totales: float = Field(0.0, ge=0.0)
    dias_trabajados_laborales: float = Field(0.0, ge=0.0)
    llenado_por: str = Field("", max_length=100, description="Nombre de quien llena el registro")
    tarifa_diaria: float | None = Field(default=None, ge=0.0, description="Bs/día por jornalero (opcional)")
    observaciones: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validar_fechas(self):
        if self.fecha_final < self.fecha_inicial:
            raise ValueError("fecha_final debe ser mayor o igual a fecha_inicial")
        return self


class JornaleroCreate(JornaleroBase):
    pass


class JornaleroUpdate(BaseModel):
    fecha_inicial: datetime | None = None
    fecha_final: datetime | None = None
    tipo_trabajador: str | None = Field(default=None, max_length=20)
    cd: str | None = Field(default=None, min_length=1, max_length=50)
    unidad: str | None = Field(default=None, max_length=100)
    area: str | None = Field(default=None, max_length=20)
    cantidad_jornaleros: float | None = Field(default=None, ge=0.0)
    horas_trabajadas: float | None = Field(default=None, ge=0.0)
    dias_trabajados_totales: float | None = Field(default=None, ge=0.0)
    dias_trabajados_laborales: float | None = Field(default=None, ge=0.0)
    llenado_por: str | None = Field(default=None, max_length=100)
    tarifa_diaria: float | None = Field(default=None, ge=0.0)
    observaciones: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validar_fechas(self):
        if self.fecha_inicial and self.fecha_final and self.fecha_final < self.fecha_inicial:
            raise ValueError("fecha_final debe ser mayor o igual a fecha_inicial")
        return self


class JornaleroResponse(JornaleroBase):
    id: str
    fecha_creacion: datetime
    estado_sincronizacion: str
    error_sincronizacion: str | None = None
    costo_total: float | None = None

    model_config = {"from_attributes": True}


class JornaleroListResponse(BaseModel):
    success: bool
    data: list[JornaleroResponse] = []
    total: int = 0
    offset: int = 0
    limit: int = 0


class OperationResponse(BaseModel):
    success: bool
    message: str
    data: JornaleroResponse | None = None


class SyncResponse(BaseModel):
    success: bool
    message: str
    detalles: dict = {}


class PushStatusResponse(BaseModel):
    success: bool
    running: bool
    message: str

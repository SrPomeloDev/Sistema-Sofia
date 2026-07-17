"""
models.py — Esquemas de validación con Pydantic v2.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

# ── Esquemas para Gestión de Camiones ─────────────────────────────────

class CamionBase(BaseModel):
    placa: str = Field(..., min_length=1, max_length=20, description="Placa única del camión")
    estado_trabajo: str = Field("Fijo", description="Ej: Fijo, Temporal")
    ruta: str = Field("local", description="Ej: local, granja, nacional")
    tipo_combustible: str = Field("GAS-GASOLINA", description="Ej: GAS-GASOLINA, DIESEL, GASOLINA")
    costo_flete: float = Field(0.0, ge=0.0, description="Costo de flete en Bs por viaje")
    sucursal: str = Field(..., description="Sucursal a la que pertenece (La Paz, Cochabamba, Santa Cruz)")
    capacidad_kg: int = Field(0, ge=0, description="Capacidad en KG")
    capacidad_maples: int = Field(0, ge=0, description="Capacidad útil en maples")
    capacidad_util_kg: float = Field(0.0, ge=0.0, description="Capacidad útil en Kg")
    sistema_camion: str = Field("SIN INFORMACIÓN", description="Sistema del camión: SIN INFORMACIÓN, HIBRIDO, SECOS, REFRIGERADO")
    estado_servicio: str = Field("EN SERVICIO", description="Estado de servicio: EN SERVICIO, FUERA DE SERVICIO, CONSULTAR")
    propietario: str = Field("", description="Nombre del propietario/chofer")
    modificado_por: str = Field("", description="Nombre de quien registra/modifica")
    modificado_por_email: str = Field("", description="Email de quien registra/modifica")

class CamionCreate(CamionBase):
    pass

class CamionUpdate(BaseModel):
    estado_trabajo: str | None = None
    ruta: str | None = None
    tipo_combustible: str | None = None
    costo_flete: float | None = None
    sucursal: str | None = None
    capacidad_kg: int | None = None
    capacidad_maples: int | None = None
    capacidad_util_kg: float | None = None
    sistema_camion: str | None = None
    estado_servicio: str | None = None
    propietario: str | None = None
    modificado_por: str | None = None
    modificado_por_email: str | None = None

class CamionResponse(CamionBase):
    fila_id: int
    nro: str | None
    estado_sincronizacion: str
    error_sincronizacion: str | None = None
    factor_0_75: float = Field(default=0.0, description="0.75 × capacidad_maples")

    class Config:
        from_attributes = True

# ── Esquemas de Sincronización y Auditoría ────────────────────────────

class UpdateSheetResponse(BaseModel):
    success: bool
    message: str
    auditoria_id: int | None = None

class AuditEntry(BaseModel):
    id: int
    fila_id: int | None = None
    accion: str
    valores: str  # JSON con los valores cambiados
    estado: str  # "pendiente", "éxito", "fallido"
    error: str | None = None
    creado_en: str

    class Config:
        from_attributes = True

class SyncStatusResponse(BaseModel):
    modo: str
    sheets_configuradas: bool
    pendientes_sincronizacion: int
    total_registros: int
    ultimo_cambio: str | None = None
    ultimo_cambio_por: str | None = None
    ultimo_cambio_email: str | None = None
    camiones_por_sucursal: dict[str, int] = {}

class FletePromedioResponse(BaseModel):
    sucursal: str
    promedio_flete: float
    total_camiones: int
    total_flete: float

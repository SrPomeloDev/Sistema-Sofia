from pydantic import BaseModel, Field
from datetime import datetime


class RutaMadreBase(BaseModel):
    sucursal: str = Field(..., min_length=1, max_length=50)
    nombre: str = Field(..., min_length=1, max_length=100)


class RutaMadreCreate(RutaMadreBase):
    pass


class RutaMadreUpdate(BaseModel):
    sucursal: str | None = Field(default=None, min_length=1, max_length=50)
    nombre: str | None = Field(default=None, min_length=1, max_length=100)

    model_config = {"extra": "forbid"}


class RutaMadreResponse(RutaMadreBase):
    id: int

    model_config = {"from_attributes": True}


class RutaHijaBase(BaseModel):
    ruta_madre_id: int
    ruta_hija: str = Field(..., min_length=1, max_length=200)
    flete: float = Field(default=0.0, ge=0.0)
    metodo: str | None = None


class RutaHijaCreate(RutaHijaBase):
    pass


class RutaHijaUpdate(BaseModel):
    ruta_hija: str | None = Field(default=None, min_length=1, max_length=200)
    flete: float | None = Field(default=None, ge=0.0)
    metodo: str | None = None

    model_config = {"extra": "forbid"}


class RutaHijaResponse(RutaHijaBase):
    id: int

    model_config = {"from_attributes": True}


class RutaMadreConHijasResponse(RutaMadreResponse):
    hijas: list[RutaHijaResponse] = []


class OperationResponse(BaseModel):
    success: bool
    message: str
    data: RutaMadreConHijasResponse | RutaMadreResponse | RutaHijaResponse | None = None

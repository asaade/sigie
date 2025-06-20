# app/db/session.py
"""
Módulo de sesión de base de datos para SIGIE: crea engine y sesiones y permite iniciar la BD.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings
from app.db.models import Base

settings = get_settings()

# Crear el engine de SQLAlchemy usando la URL de base de datos configurada (preferir PSQL si existe)
engine = create_engine(
    settings.database_url or settings.psql_database_url,
    pool_pre_ping=True,
)

# SessionLocal se usa para instanciar sesiones de base de datos
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """
    Dependencia de FastAPI para obtener/terminar sesión de base de datos.
    Ejemplo:
        db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Crea tablas en la base de datos si no existen.
    Se llama en el evento de startup de FastAPI.
    """
    Base.metadata.create_all(bind=engine)

# app/db/models.py
from sqlalchemy import Column, String, Integer, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class ItemModel(Base):
    __tablename__ = 'items'

    id = Column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text('gen_random_uuid()'),
        nullable=False
    )
    temp_id = Column(PGUUID(as_uuid=True), nullable=False, server_default=text('gen_random_uuid()'))
    status = Column(String, nullable=False, default='pending')
    payload = Column(JSONB, nullable=False)
    errors = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    warnings = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    prompt_v = Column(String, nullable=True)
    token_usage = Column(Integer, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

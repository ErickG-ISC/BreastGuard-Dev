from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from backend.models.database import Base

class User(Base):
    __tablename__ = "users"

    id=Column(Integer,primary_key=True,index=True)
    email = Column(String,unique=True,index=True)
    hashed_password=Column(String)
    full_name=Column(String)
    is_medical=Column(Boolean,default=False) ## True si es médico
    created_at=Column(DateTime(timezone=True),server_default=func.now())
    updated_at=Column(DateTime(timezone=True),on_update=func.now())
    images = relationship("MedicalImage", back_populates="user")


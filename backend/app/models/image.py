from sqlalchemy import Column,Integer,String,Float,ForeignKey,DateTime
from sqlalchemy.orm import relationship
from backend.models.database import Base

class MedicalImage(Base):
    __tablename__ = "medical_images"

    id=Column(Integer,primary_key=True,index=True)
    user_id=Column(Integer,ForeignKey("users.id"))
    image_path=Column(String) #URL en S3
    image_type=Column(String) #BUSI o mammography
    prediction = Column(String,nullable=True) #benign, malignant, etc.
    confidence=Column(Float,nullable=True)
    created_at=Column(DateTime(timezone=True),server_default=func.now())
    user=relationship("User",back_populates="images")

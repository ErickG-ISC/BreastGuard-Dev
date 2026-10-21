from pydantic import BaseModel


class ImageUploadOut(BaseModel):
    message: str
    image_id: int

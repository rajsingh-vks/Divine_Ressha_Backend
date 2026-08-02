from datetime import datetime

from pydantic import BaseModel


class HeroBannerOut(BaseModel):
    id: str
    title: str
    subtitle: str
    image_url: str
    is_active: bool = True
    display_order: int = 0
    created_at: datetime
    updated_at: datetime

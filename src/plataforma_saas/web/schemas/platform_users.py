from pydantic import BaseModel, ConfigDict, EmailStr, Field


class PlatformAdminInvite(BaseModel):
    first_name: str = Field(min_length=2, max_length=80)
    last_name: str = Field(min_length=2, max_length=80)
    email: EmailStr

    model_config = ConfigDict(extra="forbid")

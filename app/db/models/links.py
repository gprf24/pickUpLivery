# app/db/models/links.py
from sqlmodel import Field, SQLModel


class UserPharmacyLink(SQLModel, table=True):
    """
    Many-to-many link between users and pharmacies.
    - No relationships here; just a plain link table.
    - Primary key is (user_id, pharmacy_id).
    - You can leave this unused for now; it won't hurt,
      but keeps the schema ready for later.
    """

    __tablename__ = "PP_user_pharmacy_link"

    user_id: int = Field(primary_key=True, foreign_key="PP_user.id")
    pharmacy_id: int = Field(primary_key=True, foreign_key="PP_pharmacy.id")

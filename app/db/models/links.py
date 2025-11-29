from __future__ import annotations

from sqlmodel import Field, SQLModel

# app/db/models/links.py


class UserPharmacyLink(SQLModel, table=True):
    """
    Many-to-many link between users and pharmacies.

    - Plain link table, no ORM relationships.
    - Composite primary key: (user_id, pharmacy_id).
    """

    __tablename__ = "user_pharmacy_links"

    user_id: int = Field(primary_key=True, foreign_key="users.id")
    pharmacy_id: int = Field(primary_key=True, foreign_key="pharmacies.id")

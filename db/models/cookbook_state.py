from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class CookbookState(Base):
    """Личное состояние кукбука для синка между устройствами.

    Одна строка на (tg_id, key). `value` — целиком блоб ключа (как его пишет
    фронтовый Store.save), `rev` — клиентские Date.now() мс, часы last-write-wins.
    Таблица изолирована (нет FK к таблицам fashion-bot).
    """

    __tablename__ = "cookbook_state"

    tg_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rev: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

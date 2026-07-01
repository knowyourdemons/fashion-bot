# Импортируем все модели здесь — Alembic autogenerate требует
# чтобы они были зарегистрированы в Base.metadata

from db.models.user import User
from db.models.child import Child
from db.models.wardrobe import WardrobeItem
from db.models.brief_log import BriefLog
from db.models.outfit_log import OutfitLog
from db.models.events import Event
from db.models.scoring_matrix import ScoringMatrix
from db.models.taxonomy import ItemCategory, TaxonomyVersion, UnknownItem
from db.models.referrals import Referral
from db.models.admin_actions import AdminAction
from db.models.cookbook_state import CookbookState

__all__ = [
    "User",
    "Child",
    "WardrobeItem",
    "BriefLog",
    "OutfitLog",
    "Event",
    "ScoringMatrix",
    "ItemCategory",
    "TaxonomyVersion",
    "UnknownItem",
    "Referral",
    "AdminAction",
    "CookbookState",
]

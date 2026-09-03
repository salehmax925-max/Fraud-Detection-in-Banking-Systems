"""backend/app/models/__init__.py"""
from app.models.orm import (
    User,
    Transaction,
    ShapExplanation,
    ReviewQueue,
    DigitalTwinProfile,
    ThresholdConfig,
)
from app.models.auth import (
    AuthUser,
    UserPermission,
    ThresholdAudit,
    GovernanceAudit,
    SystemLog,
    UserPreference,
)

__all__ = [
    # Original models
    "User", "Transaction", "ShapExplanation",
    "ReviewQueue", "DigitalTwinProfile", "ThresholdConfig",
    # Auth & governance models
    "AuthUser", "UserPermission", "ThresholdAudit",
    "GovernanceAudit", "SystemLog", "UserPreference",
]

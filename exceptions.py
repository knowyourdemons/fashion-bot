class FashionBotError(Exception):
    """Base exception — показывается пользователю."""


class RateLimitError(FashionBotError):
    """Превышен лимит запросов."""


class PaymentError(FashionBotError):
    """Ошибка оплаты."""


class PermissionDeniedError(FashionBotError):
    """Действие недоступно на текущем плане."""


class DuplicateItemError(FashionBotError):
    """Вещь уже есть в гардеробе (perceptual hash)."""


class WardrobeFullError(FashionBotError):
    """Достигнут лимит вещей в гардеробе."""


class ItemNotFoundError(FashionBotError):
    """Вещь не найдена."""


class UserNotFoundError(FashionBotError):
    """Пользователь не найден."""


class ChildNotFoundError(FashionBotError):
    """Ребёнок не найден."""


class OnboardingIncompleteError(FashionBotError):
    """Онбординг не завершён."""


class CircuitBreakerOpenError(FashionBotError):
    """Circuit breaker открыт — сервис временно недоступен."""


class ImageTooLargeError(FashionBotError):
    """Фото превышает максимально допустимый размер (20MB)."""


class NoClothingDetectedError(FashionBotError):
    """На фото не обнаружена одежда."""

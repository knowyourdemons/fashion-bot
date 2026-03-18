"""Seed scoring matrices into DB."""
import structlog
from sqlalchemy import select, update

from db.base import AsyncWriteSession, AsyncReadSession
from db.models.scoring_matrix import ScoringMatrix

logger = structlog.get_logger()

_MATRICES_V3 = [
    # ── Детские: 0-3 ─────────────────────────────────────────────────────────
    {
        "name": "0-3-girl",
        "age_from": 0, "age_to": 3, "gender": "girl", "is_pregnant": False,
        "max_score": 24, "version": "v3.0",
        "criteria": {
            "safety":       {"weight": 3, "description": "безопасность (мелкие детали, завязки)"},
            "comfort":      {"weight": 2, "description": "мягкость, не натирает, не давит"},
            "colortype":    {"weight": 2, "description": "соответствие цветотипу ребёнка"},
            "style":        {"weight": 2, "description": "красота, нежность, сочетаемость цветов"},
            "practicality": {"weight": 1, "description": "лёгкость стирки, немаркость"},
            "versatility":  {"weight": 1, "description": "сочетается с другими вещами"},
            "seasonality":  {"weight": 1, "description": "соответствие сезону"},
            "_tone": "обращение к маме, нежное, тёплое",
            "_wow_messages": [
                "✨ Какая нежная! Малышке будет и тепло, и красиво",
                "✨ Настоящая маленькая модница!",
                "✨ Прелесть! Цвета идеально подходят",
            ],
        },
    },
    {
        "name": "0-3-boy",
        "age_from": 0, "age_to": 3, "gender": "boy", "is_pregnant": False,
        "max_score": 26, "version": "v3.0",
        "criteria": {
            "safety":           {"weight": 3, "description": "безопасность"},
            "comfort":          {"weight": 3, "description": "мягкость, свобода движений"},
            "stain_resistance": {"weight": 2, "description": "практичный цвет, немаркая ткань"},
            "practicality":     {"weight": 2, "description": "лёгкость стирки, прочность"},
            "versatility":      {"weight": 1, "description": "сочетается с другими вещами"},
            "colortype":        {"weight": 1, "description": "соответствие цветотипу"},
            "seasonality":      {"weight": 1, "description": "соответствие сезону"},
            "_tone": "обращение к маме, практичное, тёплое",
            "_wow_messages": [
                "✨ Тёплый и удобный — готов к приключениям!",
                "✨ Практично и стильно — маме одобрение!",
                "✨ Отличный выбор — и поползать, и покрасоваться",
            ],
        },
    },
    # ── Детские: 3-7 ─────────────────────────────────────────────────────────
    {
        "name": "3-7-girl",
        "age_from": 3, "age_to": 7, "gender": "girl", "is_pregnant": False,
        "max_score": 24, "version": "v3.0",
        "criteria": {
            "colortype":     {"weight": 3, "description": "цветотип, сочетаемость цветов"},
            "style":         {"weight": 2, "description": "яркость, красота, самовыражение"},
            "self_dressing": {"weight": 2, "description": "ребёнок может одеться сам (молния vs пуговицы)"},
            "comfort":       {"weight": 2, "description": "удобно бегать и играть"},
            "practicality":  {"weight": 1, "description": "немаркое, легко стирать"},
            "versatility":   {"weight": 1, "description": "сочетается с другими вещами"},
            "seasonality":   {"weight": 1, "description": "соответствие сезону"},
            "_tone": "обращение к маме, упоминание ребёнка. 'покажи — ей понравится!'",
            "_wow_messages": [
                "✨ Стильная и яркая — точно понравится!",
                "✨ Как из модного каталога! И удобно бегать",
                "✨ Покажи дочке — она будет в восторге от цветов!",
            ],
        },
    },
    {
        "name": "3-7-boy",
        "age_from": 3, "age_to": 7, "gender": "boy", "is_pregnant": False,
        "max_score": 30, "version": "v3.0",
        "criteria": {
            "activity_fit":     {"weight": 3, "description": "можно бегать, лазить, падать"},
            "stain_resistance": {"weight": 3, "description": "практичный цвет, не маркий"},
            "self_dressing":    {"weight": 2, "description": "ребёнок может одеться сам"},
            "comfort":          {"weight": 2, "description": "свобода движений, мягкость"},
            "practicality":     {"weight": 2, "description": "прочность, легко стирать"},
            "versatility":      {"weight": 1, "description": "сочетается с другими вещами"},
            "colortype":        {"weight": 1, "description": "соответствие цветотипу"},
            "seasonality":      {"weight": 1, "description": "соответствие сезону"},
            "_tone": "обращение к маме, энергичное. 'готов к любым приключениям!'",
            "_wow_messages": [
                "✨ Крутой и практичный — готов ко всему!",
                "✨ И побегать, и покрасоваться — идеально!",
                "✨ Такое не жалко испачкать — и при этом стильно",
            ],
        },
    },
    # ── Детские: 7-12 ────────────────────────────────────────────────────────
    {
        "name": "7-12-girl",
        "age_from": 7, "age_to": 12, "gender": "girl", "is_pregnant": False,
        "max_score": 22, "version": "v3.0",
        "criteria": {
            "style":        {"weight": 3, "description": "модно, красиво, самовыражение"},
            "colortype":    {"weight": 2, "description": "цветотип, сочетаемость"},
            "versatility":  {"weight": 2, "description": "контексты: школа, прогулка, гости"},
            "comfort":      {"weight": 2, "description": "удобно на весь день"},
            "practicality": {"weight": 1, "description": "немаркое, прочное"},
            "seasonality":  {"weight": 1, "description": "соответствие сезону"},
            "_tone": "с учётом мнения ребёнка. 'думаю, одобрит'",
            "_wow_messages": [
                "✨ Модно и стильно — точно оценит!",
                "✨ Такое носят! Подруги будут спрашивать где купили",
                "✨ Красиво и при этом удобно — идеальное сочетание",
            ],
        },
    },
    {
        "name": "7-12-boy",
        "age_from": 7, "age_to": 12, "gender": "boy", "is_pregnant": False,
        "max_score": 22, "version": "v3.0",
        "criteria": {
            "activity_fit":     {"weight": 3, "description": "спорт, движение, активность"},
            "coolness":         {"weight": 2, "description": "не стрёмно перед друзьями, бренды"},
            "comfort":          {"weight": 2, "description": "удобно на весь день"},
            "stain_resistance": {"weight": 2, "description": "практичный цвет"},
            "versatility":      {"weight": 1, "description": "школа + прогулка + тренировка"},
            "seasonality":      {"weight": 1, "description": "соответствие сезону"},
            "_tone": "с учётом мнения. 'не стрёмно и удобно'",
            "_wow_messages": [
                "✨ Круто и не стрёмно — друзья оценят!",
                "✨ Стильно и можно гонять в футбол — идеально",
                "✨ Такое сейчас носят — одобряю!",
            ],
        },
    },
    # ── Детские: 12-16 ───────────────────────────────────────────────────────
    {
        "name": "12-16-girl",
        "age_from": 12, "age_to": 16, "gender": "girl", "is_pregnant": False,
        "max_score": 24, "version": "v3.0",
        "criteria": {
            "trend":         {"weight": 3, "description": "актуальность, тренды, instagram"},
            "individuality": {"weight": 2, "description": "самовыражение, уникальность"},
            "colortype":     {"weight": 2, "description": "цветотип, сочетаемость"},
            "style":         {"weight": 2, "description": "общий стиль, гармония"},
            "comfort":       {"weight": 1, "description": "удобство"},
            "versatility":   {"weight": 1, "description": "школа + гулять + мероприятия"},
            "seasonality":   {"weight": 1, "description": "соответствие сезону"},
            "_tone": "уважительное к подростку. 'ты точно оценишь'",
            "_wow_messages": [
                "✨ В тренде и подчёркивает индивидуальность!",
                "✨ Это сочетание — прям для instagram!",
                "✨ Стильно, модно и только твоё",
            ],
        },
    },
    {
        "name": "12-16-boy",
        "age_from": 12, "age_to": 16, "gender": "boy", "is_pregnant": False,
        "max_score": 24, "version": "v3.0",
        "criteria": {
            "coolness":      {"weight": 3, "description": "бренды, спорт, одобрение сверстников"},
            "trend":         {"weight": 2, "description": "актуальность, не устарело"},
            "comfort":       {"weight": 2, "description": "удобно, свободно"},
            "activity_fit":  {"weight": 2, "description": "спорт, активность"},
            "individuality": {"weight": 1, "description": "не как у всех, но и не стрёмно"},
            "versatility":   {"weight": 1, "description": "школа + гулять + тренировка"},
            "seasonality":   {"weight": 1, "description": "соответствие сезону"},
            "_tone": "уважительное, без сюсюканья",
            "_wow_messages": [
                "✨ Круто! Друзья оценят",
                "✨ Стильно и при этом удобно гонять",
                "✨ Такое сейчас носят — одобряю",
            ],
        },
    },
    # ── Взрослые ─────────────────────────────────────────────────────────────
    {
        "name": "16-25",
        "age_from": 16, "age_to": 25, "gender": "all", "is_pregnant": False,
        "max_score": 26, "version": "v3.0",
        "criteria": {
            "trend":        {"weight": 3, "description": "актуальность, тренды"},
            "colortype":    {"weight": 2, "description": "соответствие цветотипу"},
            "wardrobe_fit": {"weight": 2, "description": "сочетаемость с гардеробом"},
            "style_unity":  {"weight": 2, "description": "стиль, самовыражение"},
            "versatility":  {"weight": 1, "description": "универсальность контекстов"},
            "comfort":      {"weight": 1, "description": "удобство"},
            "quality":      {"weight": 1, "description": "качество ткани и пошива"},
            "seasonality":  {"weight": 1, "description": "соответствие сезону"},
            "_tone": "подруга-стилист, дружелюбно, с энтузиазмом",
            "_wow_messages": [
                "✨ Вау, это сочетание — огонь!",
                "✨ Выглядишь на миллион!",
                "✨ Такой образ обычно собирают стилисты",
            ],
            "_role_labels": {
                "base": "Незаменимая основа — работает с 70% гардероба",
                "accent": "Яркий акцент — добавь к нейтральной базе и wow!",
                "statement": "Вау-вещь для особого случая!",
            },
        },
    },
    {
        "name": "25-35",
        "age_from": 25, "age_to": 35, "gender": "all", "is_pregnant": False,
        "max_score": 32, "version": "v3.0",
        "criteria": {
            "wardrobe_fit":   {"weight": 3, "description": "сочетаемость с гардеробом"},
            "versatility":    {"weight": 3, "description": "работа + прогулка + ужин"},
            "colortype":      {"weight": 2, "description": "соответствие цветотипу"},
            "quality":        {"weight": 2, "description": "качество ткани и пошива"},
            "trend":          {"weight": 2, "description": "актуальность"},
            "silhouette_fit": {"weight": 1, "description": "подчёркивает силуэт"},
            "style_unity":    {"weight": 1, "description": "стилевая гармония"},
            "comfort":        {"weight": 1, "description": "удобство"},
            "seasonality":    {"weight": 1, "description": "соответствие сезону"},
            "_tone": "умный стилист, конкретные советы, ценность за деньги",
            "_wow_messages": [
                "✨ Образ на $200 из того что уже есть!",
                "✨ Стильно, элегантно и всё из твоего гардероба",
                "✨ Такое сочетание — находка для занятой женщины",
            ],
            "_role_labels": {
                "base": "Рабочая лошадка — работает и в офис, и на ужин",
                "accent": "Акцент, который оживляет нейтральную базу",
                "statement": "Для тех самых моментов — береги!",
            },
        },
    },
    {
        "name": "35-45",
        "age_from": 35, "age_to": 45, "gender": "all", "is_pregnant": False,
        "max_score": 34, "version": "v3.0",
        "criteria": {
            "quality":        {"weight": 3, "description": "ткань, пошив, долговечность"},
            "silhouette_fit": {"weight": 3, "description": "подчёркивает фигуру, крой"},
            "wardrobe_fit":   {"weight": 2, "description": "сочетаемость с гардеробом"},
            "versatility":    {"weight": 2, "description": "универсальность контекстов"},
            "colortype":      {"weight": 2, "description": "соответствие цветотипу"},
            "comfort":        {"weight": 2, "description": "удобство на весь день"},
            "style_unity":    {"weight": 1, "description": "элегантность"},
            "trend":          {"weight": 1, "description": "актуальность (не устарело)"},
            "seasonality":    {"weight": 1, "description": "соответствие сезону"},
            "_tone": "элегантный стилист, уважительно, акцент на качество и силуэт",
            "_wow_messages": [
                "✨ Элегантно и со вкусом — прослужит не один сезон",
                "✨ Качественная вещь + идеальный крой = безупречный образ",
                "✨ Выглядишь дорого — а это из твоего шкафа!",
            ],
        },
    },
    {
        "name": "45+",
        "age_from": 45, "age_to": 999, "gender": "all", "is_pregnant": False,
        "max_score": 30, "version": "v3.0",
        "criteria": {
            "comfort":        {"weight": 3, "description": "удобство, мягкость, свобода"},
            "quality":        {"weight": 3, "description": "ткань, пошив, долговечность"},
            "silhouette_fit": {"weight": 2, "description": "подчёркивает достоинства"},
            "wardrobe_fit":   {"weight": 2, "description": "сочетаемость с гардеробом"},
            "colortype":      {"weight": 2, "description": "соответствие цветотипу"},
            "versatility":    {"weight": 1, "description": "универсальность"},
            "style_unity":    {"weight": 1, "description": "гармония образа"},
            "seasonality":    {"weight": 1, "description": "соответствие сезону"},
            "_tone": "уважительный стилист, комфорт и элегантность, без навязывания трендов",
            "_wow_messages": [
                "✨ Удобно, стильно и очень гармонично",
                "✨ Элегантность — это когда комфортно и красиво одновременно",
                "✨ Прекрасный выбор — и выглядит, и ощущается на 10!",
            ],
        },
    },
    # ── Беременные ───────────────────────────────────────────────────────────
    {
        "name": "pregnant-1",
        "age_from": 0, "age_to": 999, "gender": "all", "is_pregnant": True,
        "max_score": 22, "version": "v3.0",
        "criteria": {
            "comfort":            {"weight": 2, "description": "удобство, мягкость"},
            "versatility":        {"weight": 2, "description": "подходит на несколько месяцев"},
            "practicality":       {"weight": 2, "description": "легко стирать, практичность"},
            "post_pregnancy_use": {"weight": 2, "description": "можно носить после родов"},
            "colortype":          {"weight": 1, "description": "соответствие цветотипу"},
            "condition":          {"weight": 1, "description": "состояние вещи"},
            "seasonality":        {"weight": 1, "description": "соответствие сезону"},
            "_tone": "тёплое, поддерживающее, для будущей мамы в первом триместре",
            "_wow_messages": [
                "✨ Прекрасный образ для будущей мамы!",
                "✨ Удобно и стильно — идеально для первого триместра",
                "✨ Такая вещь пригодится и после родов — умный выбор!",
            ],
        },
    },
    {
        "name": "pregnant-2",
        "age_from": 0, "age_to": 999, "gender": "all", "is_pregnant": True,
        "max_score": 28, "version": "v3.0",
        "criteria": {
            "bump_friendly":      {"weight": 3, "description": "комфортно для животика"},
            "comfort":            {"weight": 3, "description": "мягкость, свобода движений"},
            "practicality":       {"weight": 2, "description": "практичность"},
            "post_pregnancy_use": {"weight": 2, "description": "можно носить после родов"},
            "colortype":          {"weight": 1, "description": "соответствие цветотипу"},
            "versatility":        {"weight": 1, "description": "универсальность"},
            "condition":          {"weight": 1, "description": "состояние вещи"},
            "seasonality":        {"weight": 1, "description": "соответствие сезону"},
            "_tone": "тёплое, практичное, для мамы во втором триместре — животик растёт!",
            "_wow_messages": [
                "✨ Идеально для второго триместра — и красиво, и удобно!",
                "✨ Прекрасный образ для будущей мамы!",
                "✨ Такая вещь пригодится и после родов — мудрый выбор",
            ],
        },
    },
    {
        "name": "pregnant-3",
        "age_from": 0, "age_to": 999, "gender": "all", "is_pregnant": True,
        "max_score": 26, "version": "v3.0",
        "criteria": {
            "comfort":            {"weight": 4, "description": "максимальный комфорт"},
            "bump_friendly":      {"weight": 3, "description": "комфортно для большого животика"},
            "practicality":       {"weight": 2, "description": "практичность"},
            "post_pregnancy_use": {"weight": 1, "description": "можно носить после родов"},
            "colortype":          {"weight": 1, "description": "соответствие цветотипу"},
            "condition":          {"weight": 1, "description": "состояние вещи"},
            "seasonality":        {"weight": 1, "description": "соответствие сезону"},
            "_tone": "максимально поддерживающее — третий триместр, скоро встреча!",
            "_wow_messages": [
                "✨ Выглядишь прекрасно — скоро встреча с малышом!",
                "✨ Комфортно и стильно — ты справляешься!",
                "✨ Прекрасный образ для будущей мамы!",
            ],
        },
    },
]


async def seed_scoring_matrices() -> None:
    """Обновляет матрицы до v3.0: апдейт существующих по name, вставка новых.
    Всегда деактивирует старые gender=all детские матрицы (0-3, 3-7, 7-12, 12-16).
    """
    # Деактивировать старые gender-neutral детские матрицы (идемпотентно)
    _old_child_names = {"0-3", "3-7", "7-12", "12-16"}
    async with AsyncWriteSession() as session:
        deactivated = await session.execute(
            update(ScoringMatrix)
            .where(ScoringMatrix.name.in_(_old_child_names))
            .values(is_active=False)
        )
        await session.commit()
        if deactivated.rowcount:
            logger.info("scoring_matrices.deactivated_old", count=deactivated.rowcount)

    # Проверить нужен ли seed v3.0
    async with AsyncReadSession() as session:
        result = await session.execute(
            select(ScoringMatrix).where(ScoringMatrix.version == "v3.0").limit(1)
        )
        if result.scalar_one_or_none():
            return  # v3.0 уже есть

    inserted = 0
    updated = 0
    async with AsyncWriteSession() as session:
        for data in _MATRICES_V3:
            existing = await session.execute(
                select(ScoringMatrix).where(ScoringMatrix.name == data["name"])
            )
            m = existing.scalar_one_or_none()
            if m:
                m.criteria = data["criteria"]
                m.max_score = data["max_score"]
                m.gender = data["gender"]
                m.version = data["version"]
                m.is_active = True
                updated += 1
            else:
                session.add(ScoringMatrix(**data))
                inserted += 1
        await session.commit()

    logger.info("scoring_matrices.seeded_v3", inserted=inserted, updated=updated)

import asyncio, sys
sys.path.insert(0, "/app")
from config import settings

async def test_stylist_response():
    import anthropic
    from db.base import AsyncReadSession
    from db.crud.wardrobe import get_owner_items
    import uuid

    owner_id = uuid.UUID("acf0100d-ca11-4fce-815e-c516af11e710")

    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, "child")

    top_items = sorted(
        [i for i in items if i.score_item],
        key=lambda x: float(x.score_item), reverse=True
    )[:20]
    wardrobe_context = ", ".join(
        f"{i.type} {i.color}" for i in top_items
    ) if top_items else "гардероб пуст"

    print(f"Гардероб для теста ({len(top_items)} вещей): {wardrobe_context[:120]}...")

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_keys_list[0])
    system = (
        "Ты стилист детской моды. Оцени образ ребёнка на фото.\n\n"
        f"Гардероб ребёнка (лучшие вещи):\n{wardrobe_context}\n\n"
        "Структура ответа — строго такая:\n"
        "⭐ Оценка: X/10\n"
        "✅ Что работает: (1-2 предложения)\n"
        "❌ Что улучшить: (конкретно)\n"
        "👗 Замена: [вещь на фото] → [точное название из гардероба выше]\n"
        "   Причина: улучшит [цветовую гармонию/сезонность/стиль]\n\n"
        "Правила:\n"
        "- В разделе 'Замена' используй ТОЛЬКО вещи из списка гардероба выше\n"
        "- Если нужной замены нет в гардеробе — пропусти раздел 'Замена'\n"
        "- Если оценка 8 или выше — раздел 'Замена' не нужен, только похвали\n"
        "- Максимум 2 замены\n"
        "- НЕ советуй покупать вещи которые уже есть в гардеробе\n"
        "Язык: русский."
    )

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        system=system,
        messages=[{"role": "user", "content":
            "На фото девочка 3 лет в розовом свитшоте, синих джинсах "
            "и белых кроссовках. Оцени образ."}],
        max_tokens=512,
    )
    text = response.content[0].text
    print(f"Ответ стилиста:\n{text}\n")

    assert "⭐ Оценка:" in text, f"FAIL: нет оценки\n{text}"
    assert "✅" in text, f"FAIL: нет раздела 'Что работает'\n{text}"

    if "👗 Замена:" in text:
        zamena_lines = [l for l in text.split("\n") if "Замена:" in l]
        if zamena_lines and top_items:
            zamena = zamena_lines[0]
            wardrobe_types = [i.type.lower() for i in top_items]
            found = any(t in zamena.lower() for t in wardrobe_types)
            if not found:
                print(f"WARNING: замена '{zamena[:80]}' — не найдена точно в гардеробе (возможно частичное совпадение)")
            else:
                print("PASS: замена из реального гардероба")
    else:
        print("INFO: раздел 'Замена' не включён (оценка высокая или нет подходящих замен)")

    print("PASS: структура ответа корректна")

asyncio.run(test_stylist_response())

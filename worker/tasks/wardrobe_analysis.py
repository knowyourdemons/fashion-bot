"""wardrobe_analysis task — analyze wardrobe health for premium users."""
import asyncio
import json
from collections import Counter

import structlog

logger = structlog.get_logger()

REDIS_TTL = 7 * 86400  # 7 days


async def run() -> None:
    """Cron trigger — weekly wardrobe health analysis for premium users."""
    logger.info("wardrobe_analysis.run.start")

    try:
        from sqlalchemy import select
        from db.base import AsyncReadSession
        from db.models.user import User
        from db.crud.wardrobe import get_owner_items
        from db.crud.children import get_children
        from core.permissions import get_effective_plan
        from core.redis import get_redis
        from services.scoring import calc_item_versatility
        import sentry_sdk

        redis = get_redis()

        async with AsyncReadSession() as session:
            result = await session.execute(
                select(User).where(
                    User.onboarding_completed.is_(True),
                    User.deleted_at.is_(None),
                    User.is_active.is_(True),
                )
            )
            all_users = list(result.scalars().all())

        eligible = [
            u for u in all_users
            if get_effective_plan(u) in ("premium", "ultra", "admin")
        ]

        analyzed = 0
        errors = 0

        for user in eligible:
            try:
                # Determine owner
                owner_id = user.id
                owner_type = "user"
                if user.segment in ("mom_girl", "mom_boy"):
                    async with AsyncReadSession() as session:
                        children = await get_children(session, user.id)
                    if children:
                        owner_id = children[0].id
                        owner_type = "child"

                async with AsyncReadSession() as session:
                    items = await get_owner_items(session, owner_id, owner_type)

                if len(items) < 10:
                    continue

                # 1. Versatility per item
                versatility_map = {}
                for item in items:
                    v = calc_item_versatility(item, items)
                    versatility_map[str(item.id)] = {
                        "type": item.type,
                        "color": item.color,
                        "category_group": item.category_group,
                        "versatility": v,
                    }

                # 2. Orphans (versatility < 2)
                orphans = [
                    {"type": info["type"], "color": info["color"]}
                    for info in versatility_map.values()
                    if info["versatility"] < 2
                ]

                # 3. Category balance
                category_counts = Counter(
                    item.category_group for item in items
                    if item.category_group not in ("base_layer", "underwear")
                )
                total_visual = sum(category_counts.values())
                imbalances = []
                if total_visual >= 10:
                    for cat, count in category_counts.items():
                        ratio = count / total_visual
                        if ratio > 0.5:
                            imbalances.append(
                                {"category": cat, "count": count, "issue": "too_many"}
                            )
                    # Check missing essentials
                    for essential in ("top", "bottom", "footwear"):
                        if category_counts.get(essential, 0) < 2:
                            imbalances.append(
                                {"category": essential, "count": category_counts.get(essential, 0), "issue": "too_few"}
                            )

                # 4. Store in Redis
                analysis = {
                    "user_id": str(user.id),
                    "total_items": len(items),
                    "orphan_count": len(orphans),
                    "orphans": orphans[:10],  # cap at 10
                    "category_counts": dict(category_counts),
                    "imbalances": imbalances,
                    "top_versatile": sorted(
                        versatility_map.values(),
                        key=lambda x: x["versatility"],
                        reverse=True,
                    )[:5],
                }
                await redis.set(
                    f"wardrobe_analysis:{user.id}",
                    json.dumps(analysis, ensure_ascii=False),
                    ex=REDIS_TTL,
                )
                analyzed += 1

            except Exception as e:
                logger.warning("wardrobe_analysis.user_error", user_id=str(user.id), error=str(e))
                sentry_sdk.capture_exception(e)
                errors += 1

            await asyncio.sleep(0.5)

        logger.info(
            "wardrobe_analysis.run.done",
            eligible=len(eligible),
            analyzed=analyzed,
            errors=errors,
        )

    except Exception as e:
        logger.error("wardrobe_analysis.run.fatal", error=str(e))
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass

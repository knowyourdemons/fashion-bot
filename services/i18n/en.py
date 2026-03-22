"""English interface strings."""

STRINGS: dict[str, str] = {
    # General
    "error.generic": "Something went wrong. Try again.",
    "error.rate_limit": "Too many requests. Wait a moment.",
    "error.permission": "This feature isn't available on your plan.",
    "error.not_found": "Not found.",

    # Onboarding
    "onboarding.welcome": (
        "Hey! 👋 I'm Kassi — your personal stylist.\n\n"
        "Every morning I'll send you a ready outfit based on the weather "
        "from clothes already in your closet.\n\n"
        "Let's get to know each other in 2 minutes? 😊"
    ),
    "onboarding.city": "What city do you live in? 🏙\n\nNeeded for weather forecast",

    # Wardrobe
    "wardrobe.empty": "Your wardrobe is empty! 📸 Take a photo of your first item.",
    "wardrobe.add.success": "✅ {type} {color} added!",
    "wardrobe.add.analyzing": "✨ Analyzing...",

    # Brief
    "brief.good_morning": "Good morning, {name}!",
    "brief.outfit_idea": "💡 Today's idea:",
    "brief.wore_button": "👍 Wore it",
    "brief.reroll_button": "🔄 Another",
    "brief.ask_friend_button": "📤 Ask friend",

    # Boost
    "boost.start": "📸 Take a photo in your outfit — I'll tell you how you look!\n\nMirror selfie or full-length photo 🪞",
    "boost.fallback": "You look amazing! Go confidently! 🔥",

    # Fitting
    "fitting.start": "📸 Take a photo of the item in the store — I'll tell you if it fits your wardrobe!",
    "fitting.limit": "🛍 Fitting limit: {limit}/month. Try next month!",

    # Challenge
    "challenge.start": (
        "🏆 Challenge started!\n\n"
        "Your capsule: {count} items → {combos} combinations!\n"
        "5 outfits in 10 days. Your pace.\n\n"
        "First outfit comes in the morning brief! ✨"
    ),
    "challenge.complete": (
        "🏆 Challenge complete!\n\n"
        "5 outfits · {count} items · 0 purchases\n"
        "Used {used} of {count} ({pct}%)\n\n"
        "Your closet is more powerful than you think! ✨"
    ),

    # Weekly
    "weekly.header": "📅 Weekly plan from Kassi",
    "weekly.teaser": "📅 Weekly plan is ready!\n\nWith Premium — 5 outfits every day, no repeats, weather-based.",

    # Profile
    "profile.wardrobe_math": "📊 {count} items → {combos} combinations",

    # Menu
    "menu.outfit": "✨ What to wear",
    "menu.wardrobe": "👗 Wardrobe",
    "menu.chat": "💬 Ask Kassi",
    "menu.fitting": "🛍 Will it fit?",
    "menu.profile": "👤 Profile",
    "menu.boost": "💪 How do I look?",
}

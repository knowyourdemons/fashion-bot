"""English interface strings."""

STRINGS: dict[str, str] = {
    # General
    "error.generic": "Something went wrong. Try again.",
    "error.rate_limit": "Too many requests. Wait a moment.",
    "error.permission": "This feature isn't available on your plan.",
    "error.not_found": "Not found.",

    # Wardrobe (base)
    "wardrobe.add.prompt": "Send a photo of an item 📸",
    "wardrobe.add.no_clothing": "Can't see clothing in the photo. Send a photo with clothes.",
    "wardrobe.add.duplicate": "This item is already in your wardrobe!",
    "wardrobe.add.success": "Added to wardrobe ✅",
    "wardrobe.full": "Wardrobe full ({used}/{max} items).",
    "wardrobe.full.free": (
        "👗 Wardrobe full — {used}/{max} items.\n\n"
        "✨ Premium unlocks up to 500 items + unlimited daily photos.\n"
        "👉 /subscribe — 14 days free"
    ),

    # Feedback
    "feedback.thanks_up": "Great! Glad you liked it 👍",
    "feedback.thanks_down": "Got it, I'll adjust next time 👎",

    # Billing (base)
    "billing.subscribe": "Choose subscription period:",
    "billing.premium_monthly":   "💎 Premium — $9/mo (700 ⭐)",
    "billing.premium_quarterly": "💎 Premium — $22/quarter (1700 ⭐)",
    "billing.premium_yearly":    "💎 Premium — $72/year (5500 ⭐) 🏆",
    "billing.success": "Subscription active! Thank you ✨",
    "billing.cancelled": "Subscription cancelled.",

    # Trial
    "trial.activated": (
        "🎁 14 days Premium — free!\n\n"
        "All features unlocked:\n"
        "📅 Morning Brief every day\n"
        "📸 30 photos to wardrobe\n"
        "💬 20 stylist questions\n\n"
        "Enjoy! 🌟"
    ),
    "trial.expired": (
        "🎁 Trial period ended.\n\n"
        "To continue without limits — choose a plan:\n"
        "👉 /subscribe"
    ),

    # Shopping
    "shopping.premium_only": (
        "🛍 Shopping list is a Premium feature.\n\n"
        "Kassi will analyze your wardrobe and suggest what to buy "
        "based on season and color type.\n\n"
        "👉 /subscribe — 14 days free"
    ),
    "shopping.too_few_items": "Add at least 5 items to your wardrobe first 📸",
    "shopping.generating": "🔍 Looking at your wardrobe...",
    "shopping.header": "🛍 What to buy for {season}:\n\n{list}",
    "shopping.empty_result": "Your wardrobe looks great — nothing urgent to buy 👍",
    "shopping.error": "Couldn't analyze wardrobe. Try later.",

    # Referral
    "referral.info": (
        "🎁 Invite a friend!\n\n"
        "Your code: {code}\n"
        "Share the link — your friend gets 14 days Premium free."
    ),

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

    # Help
    "help.text": (
        "Hey! I'm Kassi — your personal stylist 👗\n\n"
        "📸 Send a photo — I'll add it to your wardrobe\n"
        "✨ What to wear — outfit by weather\n"
        "💬 Ask a question — style advice\n"
        "🛍 Will it fit? — check a purchase\n"
        "👤 Profile — capsule, packing, settings\n\n"
        "Every morning at 07:00 — a ready outfit!\n\n"
        "Tips:\n"
        "• Photograph items one at a time on light background\n"
        "• More items = more interesting outfits\n"
        "• Tap 👍 Wore it — I'll remember"
        "\n\nPremium:\n"
        "👗 /capsule — seasonal capsule\n"
        "🧳 /travel — pack your suitcase\n"
        "📊 Monthly report — arrives on the 1st"
    ),

    # ── Wardrobe ──
    "wardrobe.looking": "✨ Let me see...",
    "wardrobe.looking_photo": "✨ Looking at photo {n} of {total}...",
    "wardrobe.looking_multi": "✨ Got {count} photos. Looking...",
    "wardrobe.looking_multi_limit": "✨ Got {received} photos — taking first {total}. Looking...",
    "wardrobe.outfit_picking": "✨ Picking an outfit...",
    "wardrobe.outfit_ready": "Outfit ready!",
    "wardrobe.outfit_timeout": "⏱ Took too long. Try again!",
    "wardrobe.outfit_busy": "⏳ Kassi is busy right now. Try in a couple minutes!",
    "wardrobe.photo_timeout": "⏱ Photo took too long to process. Try again.",
    "wardrobe.photo_expired": "⏱ Time's up. Send the photo again.",
    "wardrobe.photo_send_fail": "Couldn't download the photo. Try again 📸",
    "wardrobe.photo_send_file": "Send a photo, not a file 📸",
    "wardrobe.photo_bad_network": "🌐 Network issue. Try in a minute.",
    "wardrobe.photo_bad_quality": "😔 Couldn't make out the item. Try a lighter background.",
    "wardrobe.kassi_resting": "Kassi is taking a break. Try again soon!",
    "wardrobe.colortype_looking": "🔍 Checking your color type...",
    "wardrobe.need_start": "Set up first: /start",
    "wardrobe.evaluating": "⭐ Rating...",
    "wardrobe.eval_failed": "Couldn't rate the outfit. Try again.",
    "wardrobe.photo_action": "What should I do with the photo?",
    "wardrobe.add_hint": "📸 Send a photo — I'll add it to your wardrobe!",
    "wardrobe.gap_analyzing": "📋 Looking at your wardrobe...",
    "wardrobe.gap_running": "⏳ Already looking, one moment...",
    "wardrobe.gap_complete": "✅ Your wardrobe is set for the season!",
    "wardrobe.remaining": "📸 {n} more — and I'll build your first outfit!",
    "wardrobe.selfie_skip": "OK! When you're ready — go to Profile → Color type 🎨",
    "wardrobe.colortype_set": "✨ {name} — {label}\nNow I'll pick colors that suit you!",
    "wardrobe.milestone_3": "🎉 3 items! Building tomorrow's outfit...",
    "wardrobe.milestone_3_mini": "🎉 Mini outfit unlocked! Building...",
    "wardrobe.milestone_5": "🎉 5 items! Want more accurate colors?\nSend a selfie — I'll find your color type!",
    "wardrobe.milestone_7": "🎉 Your first full outfit!",
    "wardrobe.milestone_10": "🎉 10 items — great base!",
    "wardrobe.milestone_done": "🎉 Wardrobe ready! First outfit tomorrow morning.",

    # ── Billing ──
    "billing.unknown_plan": "Unknown plan",
    "billing.need_start": "Sign in first: /start",
    "billing.card_unavailable": "Card payment temporarily unavailable.",
    "billing.create_error": "Couldn't create payment. Try again.",
    "billing.payment_received_no_user": "✅ Payment received! Type /start to update.",
    "billing.payment_db_error": "✅ Payment received, but activation error.\nType /start — we'll fix it.",
    "billing.activated": "✅ Premium activated for {period}!\nAll features unlocked. Welcome! 🎉",
    "billing.stay_free": "OK! You can always come back to Premium 💎",
    "billing.your_plan": "Your plan: {plan}{days}",

    # ── Brief ──
    "brief.rerolling": "🔄 Finding another option...",
    "brief.share_hint": "📤 Forward the image above — it has everything 👗",
    "brief.share_hint_short": "📤 Forward the image above 👗",

    # ── Profile ──
    "profile.colortype_updated": "✅ Color type updated: {label}",
    "profile.girl_or_boy": "Girl or boy? 🎀",
    "profile.child_name": "What's {whom}'s name? 👶\n(or 'cancel')",
    "profile.child_error": "Something went wrong 🤔 Try again via /profile",
    "profile.save_error": "Save error 😔 Try again",
    "profile.prefs_saved": "✅ Preferences saved! Outfits will be more accurate 🎯",

    # ── Onboarding ──
    "onboarding.resume": "Continue where we left off?",
    "onboarding.who_for": "Hey! I'm Kassi — your stylist 👗\nWho are we styling for?",
    "onboarding.your_name": "What's your name?",
    "onboarding.child_name_ask": "What's their name?",
    "onboarding.enter_name": "Enter name:",
    "onboarding.child_age": "How old?",
    "onboarding.age_error": "Didn't get that 🤔 Write age as a number (e.g. 3)",
    "onboarding.enter_city": "Enter city name:",
    "onboarding.refine_city": "Which city exactly?",

    # ── Ask friend ──
    "ask_friend.share_hint": "📤 Forward the image to a friend 👗",
    "ask_friend.vote_unavailable": "Voting unavailable 😔",
    "ask_friend.vote_closed": "Voting closed 😊",
    "ask_friend.load_failed": "Couldn't load the outfit 😔",

    # ── Text handler ──
    "text.cancelled": "Cancelled ✅",
    "text.city_not_found": "Couldn't find that city 🤔\nTry another spelling or type 'cancel'",
    "text.city_updated": "✅ City updated: {city}",
    "text.size_clothing_range": "Clothing size should be 56–176",
    "text.size_shoe_range": "Shoe size should be 15–45",
    "text.size_parse_error": "Didn't get the size 🤔 Example: '104' or '104 27'",
    "text.size_save_error": "Error saving size. Try again.",
    "text.size_updated": "✅ Size updated: {details}",

    # ── Fitting ──
    "fitting.looking": "✨ Let me check...",

    # ── Boost ──
    "boost.evaluating": "✨ Checking your look...",

    # ── Challenge / Quiz ──
    "challenge.later": "OK, challenge can wait! I'll remind you later 💪",
    "quiz.later": "OK, quiz can wait! I'll remind you in a few days 😊",

    # ── Shopping ──
    "shopping.already_running": "Already looking, one moment...",

    # ── Browser ──
    "browser.item_not_found": "Item not found.",
    "browser.deleted": "Deleted",
    "browser.unknown_season": "Unknown season",

    # Menu
    "menu.outfit": "✨ What to wear",
    "menu.wardrobe": "👗 Wardrobe",
    "menu.chat": "💬 Ask Kassi",
    "menu.fitting": "🛍 Will it fit?",
    "menu.profile": "👤 Profile",
    "menu.boost": "💪 How do I look?",

    # Capsule
    "capsule.premium_gate": (
        "👗 Seasonal capsule is a Premium feature!\n\n"
        "Kassi picks the best items for the season and shows how many outfits you can make.\n\n"
        "👉 /subscribe — 14 days free trial"
    ),
    "capsule.too_few": "Add at least 5 items to your wardrobe first 📸",
    "capsule.result": "👗 {season} capsule: {count} items → {combos} combinations!\n\nPut the rest in a box — and enjoy! ✨",
    "capsule.title": "Capsule for",
    "capsule.your": "Your",
    "capsule.combos_word": "combinations",
    "capsule.share_btn": "📤 Share",
    "capsule.ok_btn": "👍 Love it!",
    "capsule.thanks": "Glad you like it!",
    "capsule.share_hint": "Forward this card to a friend — let them build a capsule too! 💫",
    "capsule.profile_btn": "👗 My capsule",

    # Travel
    "travel.premium_gate": (
        "🧳 Travel packing is a Premium feature!\n\n"
        "Tell me where you're going — I'll pack a compact suitcase from your wardrobe.\n\n"
        "👉 /subscribe — 14 days free trial"
    ),
    "travel.ask_city": "🧳 Let's pack your suitcase!\n\nWhere are you going?",
    "travel.city_placeholder": "City, e.g. Barcelona",
    "travel.invalid_city": "Please enter a city name 🏙",
    "travel.ask_days": "🧳 {city} — great choice!\n\n📅 How many days?",
    "travel.ask_occasions": "🧳 {city}, {days} days\n\nWhat are your plans? (tap several)",
    "travel.build_btn": "✅ Pack my suitcase!",
    "travel.result_header": "🧳 Suitcase: {city}, {days} days",

    # Monthly Report
    "report.caption": (
        "📊 Your style: {month}\n\n"
        "{outfits} outfits from {used} items — "
        "you use {pct}% of your wardrobe!\n\n"
        "💰 Estimated savings: ~€{savings}"
    ),
    "report.share_btn": "📤 Share",
    "report.ok_btn": "👍 Cool!",
    "report.teaser": (
        "📊 Your monthly style report is ready!\n\n"
        "Premium includes full analytics: outfit count, savings, style trends.\n\n"
        "👉 /subscribe"
    ),

    # Language
    "lang.choose": "🌍 Choose language:",
    "lang.changed": "✅ Language updated!",

    # Paywall — conversion-boosting messages
    "paywall.value_proof": (
        "In {days} days you wore {outfits} outfits from {items} items.\n\n"
        "Premium = daily outfits + capsule + travel packing.\n"
        "Stylist: ~$300. Kassi: $9/mo.\n\n"
        "👉 /subscribe"
    ),
    "paywall.loss_aversion": (
        "Kassi knows you {knows_pct}%.\n"
        "With Premium the progress continues — outfits get more accurate.\n"
        "Without Premium — only Tue & Thu.\n\n"
        "👉 /subscribe"
    ),

    # Wardrobe diversity nudge
    "nudge.add_more_items": (
        "💡 {count} items → {combos} combinations.\n"
        "With {target} items you'll have ~{estimate}! Snap more 📸"
    ),
}

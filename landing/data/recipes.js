/* ============================================================
   База рецептов. window.RECIPES — массив объектов.
   Подгружается БЕЗ fetch, чтобы работало и под file://.
   Полное наполнение (~100-120, все кухни мира) — шаг 11.
   Это seed-набор для разработки/проверки логики.
   ------------------------------------------------------------
   Модель:
   { id, title, forKid, category, cuisine, photo, time, difficulty,
     baseServings, tags:[], ingredients:[{name,qty,unit,group,staple}],
     steps:[{text, timer?}], notes }
   qty:null + unit:"по вкусу" — не пересчитывается порциями.
   timer — секунды (авто-кнопка таймера в шаге).
   group — раздел магазина для списка покупок.
   ============================================================ */
window.RECIPES = [
  {
    id: "cacio-e-pepe", title: "Cacio e Pepe", forKid: false,
    category: "Основное", cuisine: "Итальянская", photo: "",
    time: 15, difficulty: 1, baseServings: 2, tags: ["быстро", "паста", "сыр"],
    ingredients: [
      { name: "Спагетти", qty: 200, unit: "г", group: "Бакалея", staple: false },
      { name: "Пекорино романо", qty: 80, unit: "г", group: "Молочное", staple: false },
      { name: "Чёрный перец", qty: null, unit: "по вкусу", group: "Специи", staple: true },
      { name: "Соль", qty: null, unit: "по вкусу", group: "Специи", staple: true }
    ],
    steps: [
      { text: "Отварите спагетти в подсоленной воде 8 минут до аль денте.", timer: 480 },
      { text: "Натрите пекорино, крупно намелите чёрный перец на сухой сковороде." },
      { text: "Смешайте пасту с сыром, добавляя крахмальную воду до кремовой эмульсии." }
    ], notes: ""
  },
  {
    id: "tajine-kuritsa-limon", title: "Тажин с курицей и лимоном", forKid: false,
    category: "Основное", cuisine: "Марокканская", photo: "",
    time: 75, difficulty: 2, baseServings: 4, tags: ["тушёное", "пряное", "курица"],
    ingredients: [
      { name: "Куриные бёдра", qty: 800, unit: "г", group: "Мясо", staple: false },
      { name: "Лук", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Солёный лимон", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Оливки зелёные", qty: 100, unit: "г", group: "Бакалея", staple: false },
      { name: "Имбирь молотый", qty: 1, unit: "ч.л.", group: "Специи", staple: false },
      { name: "Куркума", qty: 1, unit: "ч.л.", group: "Специи", staple: false },
      { name: "Шафран", qty: 1, unit: "щепотка", group: "Специи", staple: false },
      { name: "Кинза", qty: 1, unit: "пучок", group: "Овощи", staple: false },
      { name: "Оливковое масло", qty: 3, unit: "ст.л.", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Обжарьте курицу с луком и специями на оливковом масле до золотистого цвета." },
      { text: "Влейте стакан воды, добавьте шафран, накройте и тушите 45 минут.", timer: 2700 },
      { text: "Добавьте дольки солёного лимона и оливки, томите ещё 15 минут.", timer: 900 },
      { text: "Посыпьте рубленой кинзой перед подачей." }
    ], notes: ""
  },
  {
    id: "syrniki", title: "Сырники", forKid: true,
    category: "Завтрак", cuisine: "Русская", photo: "",
    time: 25, difficulty: 1, baseServings: 3, tags: ["детское", "творог", "сладкое"],
    ingredients: [
      { name: "Творог", qty: 400, unit: "г", group: "Молочное", staple: false },
      { name: "Яйцо", qty: 1, unit: "шт", group: "Молочное", staple: false },
      { name: "Мука", qty: 3, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Сахар", qty: 2, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Соль", qty: null, unit: "щепотка", group: "Специи", staple: true }
    ],
    steps: [
      { text: "Разомните творог с яйцом, сахаром и солью." },
      { text: "Добавьте муку, сформуйте небольшие лепёшки." },
      { text: "Обжарьте на среднем огне по 3 минуты с каждой стороны.", timer: 180 }
    ], notes: ""
  },
  {
    id: "tom-yum", title: "Том Ям с креветками", forKid: false,
    category: "Суп", cuisine: "Тайская", photo: "",
    time: 35, difficulty: 2, baseServings: 4, tags: ["острое", "суп", "морепродукты"],
    ingredients: [
      { name: "Креветки", qty: 300, unit: "г", group: "Мясо", staple: false },
      { name: "Шампиньоны", qty: 200, unit: "г", group: "Овощи", staple: false },
      { name: "Лемонграсс", qty: 2, unit: "стебля", group: "Овощи", staple: false },
      { name: "Галангал", qty: 4, unit: "ломтика", group: "Овощи", staple: false },
      { name: "Паста том ям", qty: 2, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Кокосовое молоко", qty: 200, unit: "мл", group: "Бакалея", staple: false },
      { name: "Лайм", qty: 1, unit: "шт", group: "Овощи", staple: false }
    ],
    steps: [
      { text: "Вскипятите 1 л воды с лемонграссом и галангалом, варите 5 минут.", timer: 300 },
      { text: "Добавьте пасту том ям и грибы, варите 5 минут.", timer: 300 },
      { text: "Введите креветки и кокосовое молоко, готовьте 3 минуты.", timer: 180 },
      { text: "Заправьте соком лайма перед подачей." }
    ], notes: ""
  },
  {
    id: "guacamole", title: "Гуакамоле", forKid: false,
    category: "Закуска", cuisine: "Мексиканская", photo: "",
    time: 10, difficulty: 1, baseServings: 4, tags: ["быстро", "веган", "соус"],
    ingredients: [
      { name: "Авокадо", qty: 3, unit: "шт", group: "Овощи", staple: false },
      { name: "Лайм", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Красный лук", qty: 0.5, unit: "шт", group: "Овощи", staple: false },
      { name: "Кинза", qty: 0.5, unit: "пучок", group: "Овощи", staple: false },
      { name: "Соль", qty: null, unit: "по вкусу", group: "Специи", staple: true }
    ],
    steps: [
      { text: "Разомните мякоть авокадо вилкой." },
      { text: "Добавьте мелко рубленый лук, кинзу, сок лайма и соль, перемешайте." }
    ], notes: ""
  },

  /* ===================== Итальянская ===================== */
  {
    id: "carbonara", title: "Спагетти карбонара", forKid: false,
    category: "Основное", cuisine: "Итальянская", photo: "",
    time: 20, difficulty: 2, baseServings: 2, tags: ["паста", "яйцо", "быстро"],
    ingredients: [
      { name: "Спагетти", qty: 200, unit: "г", group: "Бакалея", staple: false },
      { name: "Гуанчале или бекон", qty: 120, unit: "г", group: "Мясо", staple: false },
      { name: "Желток", qty: 3, unit: "шт", group: "Молочное", staple: false },
      { name: "Пармезан", qty: 50, unit: "г", group: "Молочное", staple: false },
      { name: "Чёрный перец", qty: null, unit: "по вкусу", group: "Специи", staple: true }
    ],
    steps: [
      { text: "Отварите спагетти аль денте 9 минут.", timer: 540 },
      { text: "Обжарьте нарезанный гуанчале до хруста." },
      { text: "Смешайте желтки с тёртым пармезаном и перцем." },
      { text: "Соедините горячую пасту с гуанчале, снимите с огня, влейте яичную смесь и крахмальную воду до кремовости." }
    ], notes: ""
  },
  {
    id: "lasagna-bolognese", title: "Лазанья болоньезе", forKid: true,
    category: "Основное", cuisine: "Итальянская", photo: "",
    time: 90, difficulty: 3, baseServings: 6, tags: ["запеканка", "мясо", "праздничное"],
    ingredients: [
      { name: "Листы лазаньи", qty: 250, unit: "г", group: "Бакалея", staple: false },
      { name: "Фарш говяжий", qty: 500, unit: "г", group: "Мясо", staple: false },
      { name: "Томаты в собственном соку", qty: 400, unit: "г", group: "Бакалея", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Морковь", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Молоко", qty: 500, unit: "мл", group: "Молочное", staple: false },
      { name: "Сливочное масло", qty: 50, unit: "г", group: "Молочное", staple: false },
      { name: "Мука", qty: 50, unit: "г", group: "Бакалея", staple: true },
      { name: "Пармезан", qty: 80, unit: "г", group: "Молочное", staple: false }
    ],
    steps: [
      { text: "Потушите фарш с луком и морковью, добавьте томаты, томите 30 минут.", timer: 1800 },
      { text: "Сварите бешамель: масло + мука + молоко, помешивая до загустения." },
      { text: "Соберите слои: соус болоньезе, листы, бешамель, пармезан." },
      { text: "Запекайте при 190° 35 минут.", timer: 2100 }
    ], notes: ""
  },
  {
    id: "risotto-funghi", title: "Ризотто с грибами", forKid: false,
    category: "Основное", cuisine: "Итальянская", photo: "",
    time: 35, difficulty: 2, baseServings: 3, tags: ["рис", "грибы", "вегетарианское"],
    ingredients: [
      { name: "Рис арборио", qty: 250, unit: "г", group: "Бакалея", staple: false },
      { name: "Белые грибы или шампиньоны", qty: 300, unit: "г", group: "Овощи", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Белое вино", qty: 100, unit: "мл", group: "Бакалея", staple: false },
      { name: "Овощной бульон", qty: 1, unit: "л", group: "Бакалея", staple: true },
      { name: "Пармезан", qty: 60, unit: "г", group: "Молочное", staple: false },
      { name: "Сливочное масло", qty: 40, unit: "г", group: "Молочное", staple: false }
    ],
    steps: [
      { text: "Обжарьте лук, добавьте рис, прогрейте 2 минуты.", timer: 120 },
      { text: "Влейте вино, выпарьте. Добавляйте бульон половниками, помешивая, 18 минут.", timer: 1080 },
      { text: "Вмешайте обжаренные грибы, масло и пармезан, дайте настояться 2 минуты." }
    ], notes: ""
  },
  {
    id: "pizza-margherita", title: "Пицца Маргарита", forKid: true,
    category: "Выпечка", cuisine: "Итальянская", photo: "",
    time: 40, difficulty: 2, baseServings: 2, tags: ["тесто", "сыр", "детское"],
    ingredients: [
      { name: "Мука", qty: 300, unit: "г", group: "Бакалея", staple: true },
      { name: "Дрожжи сухие", qty: 5, unit: "г", group: "Бакалея", staple: false },
      { name: "Томатный соус", qty: 150, unit: "г", group: "Бакалея", staple: false },
      { name: "Моцарелла", qty: 200, unit: "г", group: "Молочное", staple: false },
      { name: "Базилик", qty: 1, unit: "пучок", group: "Овощи", staple: false },
      { name: "Оливковое масло", qty: 2, unit: "ст.л.", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Замесите тесто, дайте подойти 1 час.", timer: 3600 },
      { text: "Раскатайте, смажьте соусом, выложите моцареллу." },
      { text: "Выпекайте при 250° 10 минут, украсьте базиликом.", timer: 600 }
    ], notes: ""
  },
  {
    id: "tiramisu", title: "Тирамису", forKid: false,
    category: "Десерт", cuisine: "Итальянская", photo: "",
    time: 30, difficulty: 2, baseServings: 6, tags: ["без выпечки", "кофе", "праздничное"],
    ingredients: [
      { name: "Маскарпоне", qty: 500, unit: "г", group: "Молочное", staple: false },
      { name: "Печенье савоярди", qty: 200, unit: "г", group: "Бакалея", staple: false },
      { name: "Яйцо", qty: 4, unit: "шт", group: "Молочное", staple: false },
      { name: "Сахар", qty: 100, unit: "г", group: "Бакалея", staple: true },
      { name: "Эспрессо", qty: 300, unit: "мл", group: "Бакалея", staple: false },
      { name: "Какао", qty: 2, unit: "ст.л.", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Взбейте желтки с сахаром, вмешайте маскарпоне, затем белки." },
      { text: "Обмакните савоярди в кофе, выложите слой, крем, повторите." },
      { text: "Уберите в холодильник на 4 часа, посыпьте какао." }
    ], notes: ""
  },

  /* ===================== Русская ===================== */
  {
    id: "borsch", title: "Борщ", forKid: true,
    category: "Суп", cuisine: "Русская", photo: "",
    time: 90, difficulty: 2, baseServings: 6, tags: ["суп", "свёкла", "сытное"],
    ingredients: [
      { name: "Говядина на кости", qty: 600, unit: "г", group: "Мясо", staple: false },
      { name: "Свёкла", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Капуста", qty: 300, unit: "г", group: "Овощи", staple: false },
      { name: "Картофель", qty: 3, unit: "шт", group: "Овощи", staple: false },
      { name: "Морковь", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Томатная паста", qty: 2, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Сметана", qty: null, unit: "для подачи", group: "Молочное", staple: false }
    ],
    steps: [
      { text: "Сварите бульон из говядины 60 минут.", timer: 3600 },
      { text: "Спассеруйте свёклу, морковь, лук с томатной пастой." },
      { text: "Добавьте в бульон картофель и капусту, варите 15 минут, затем заправку, ещё 10 минут.", timer: 900 },
      { text: "Подавайте со сметаной." }
    ], notes: ""
  },
  {
    id: "pelmeni", title: "Пельмени", forKid: true,
    category: "Основное", cuisine: "Русская", photo: "",
    time: 75, difficulty: 2, baseServings: 4, tags: ["тесто", "мясо", "детское"],
    ingredients: [
      { name: "Мука", qty: 400, unit: "г", group: "Бакалея", staple: true },
      { name: "Яйцо", qty: 1, unit: "шт", group: "Молочное", staple: false },
      { name: "Фарш свино-говяжий", qty: 400, unit: "г", group: "Мясо", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Соль", qty: null, unit: "по вкусу", group: "Специи", staple: true }
    ],
    steps: [
      { text: "Замесите тесто из муки, яйца и воды, дайте отдохнуть 30 минут.", timer: 1800 },
      { text: "Смешайте фарш с рубленым луком и солью." },
      { text: "Слепите пельмени, отварите в подсолённой воде 7 минут после всплытия.", timer: 420 }
    ], notes: ""
  },
  {
    id: "olivier", title: "Салат Оливье", forKid: true,
    category: "Салат", cuisine: "Русская", photo: "",
    time: 40, difficulty: 1, baseServings: 6, tags: ["салат", "праздничное"],
    ingredients: [
      { name: "Картофель", qty: 4, unit: "шт", group: "Овощи", staple: false },
      { name: "Морковь", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Яйцо", qty: 4, unit: "шт", group: "Молочное", staple: false },
      { name: "Варёная колбаса", qty: 300, unit: "г", group: "Мясо", staple: false },
      { name: "Солёные огурцы", qty: 3, unit: "шт", group: "Овощи", staple: false },
      { name: "Зелёный горошек", qty: 200, unit: "г", group: "Бакалея", staple: false },
      { name: "Майонез", qty: 150, unit: "г", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Отварите картофель, морковь и яйца, остудите.", timer: 1500 },
      { text: "Нарежьте всё кубиком, добавьте горошек." },
      { text: "Заправьте майонезом, посолите по вкусу." }
    ], notes: ""
  },
  {
    id: "bliny", title: "Блины", forKid: true,
    category: "Завтрак", cuisine: "Русская", photo: "",
    time: 30, difficulty: 1, baseServings: 4, tags: ["детское", "сладкое", "завтрак"],
    ingredients: [
      { name: "Молоко", qty: 500, unit: "мл", group: "Молочное", staple: false },
      { name: "Мука", qty: 200, unit: "г", group: "Бакалея", staple: true },
      { name: "Яйцо", qty: 2, unit: "шт", group: "Молочное", staple: false },
      { name: "Сахар", qty: 2, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Растительное масло", qty: 2, unit: "ст.л.", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Взбейте яйца с сахаром, влейте молоко, всыпьте муку, размешайте до однородности." },
      { text: "Добавьте масло. Жарьте тонкие блины на горячей сковороде по 1 минуте с каждой стороны.", timer: 60 }
    ], notes: ""
  },
  {
    id: "kotleti", title: "Домашние котлеты", forKid: true,
    category: "Основное", cuisine: "Русская", photo: "",
    time: 40, difficulty: 1, baseServings: 4, tags: ["мясо", "детское"],
    ingredients: [
      { name: "Фарш свино-говяжий", qty: 600, unit: "г", group: "Мясо", staple: false },
      { name: "Батон", qty: 100, unit: "г", group: "Бакалея", staple: false },
      { name: "Молоко", qty: 100, unit: "мл", group: "Молочное", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Яйцо", qty: 1, unit: "шт", group: "Молочное", staple: false },
      { name: "Панировочные сухари", qty: 50, unit: "г", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Замочите батон в молоке, отожмите." },
      { text: "Смешайте фарш с батоном, тёртым луком, яйцом и солью, отбейте." },
      { text: "Сформуйте котлеты, обваляйте в сухарях, жарьте по 4 минуты с каждой стороны.", timer: 240 }
    ], notes: ""
  },
  {
    id: "syrniki-zapechennye", title: "Запеканка творожная", forKid: true,
    category: "Завтрак", cuisine: "Русская", photo: "",
    time: 50, difficulty: 1, baseServings: 4, tags: ["детское", "творог", "запеканка"],
    ingredients: [
      { name: "Творог", qty: 500, unit: "г", group: "Молочное", staple: false },
      { name: "Яйцо", qty: 3, unit: "шт", group: "Молочное", staple: false },
      { name: "Манка", qty: 4, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Сахар", qty: 4, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Изюм", qty: 50, unit: "г", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Смешайте творог с яйцами, манкой, сахаром и изюмом." },
      { text: "Дайте манке набухнуть 15 минут.", timer: 900 },
      { text: "Запекайте при 180° 35 минут до румяной корочки.", timer: 2100 }
    ], notes: ""
  },

  /* ===================== Грузинская ===================== */
  {
    id: "khachapuri-imeruli", title: "Хачапури по-имеретински", forKid: true,
    category: "Выпечка", cuisine: "Грузинская", photo: "",
    time: 60, difficulty: 2, baseServings: 4, tags: ["сыр", "тесто"],
    ingredients: [
      { name: "Мука", qty: 400, unit: "г", group: "Бакалея", staple: true },
      { name: "Мацони или кефир", qty: 200, unit: "мл", group: "Молочное", staple: false },
      { name: "Сулугуни", qty: 400, unit: "г", group: "Молочное", staple: false },
      { name: "Дрожжи сухие", qty: 5, unit: "г", group: "Бакалея", staple: false },
      { name: "Яйцо", qty: 1, unit: "шт", group: "Молочное", staple: false }
    ],
    steps: [
      { text: "Замесите мягкое тесто, дайте подойти 40 минут.", timer: 2400 },
      { text: "Натрите сулугуни, заверните в лепёшку, раскатайте." },
      { text: "Выпекайте при 220° 15 минут, смажьте маслом.", timer: 900 }
    ], notes: ""
  },
  {
    id: "khinkali", title: "Хинкали", forKid: false,
    category: "Основное", cuisine: "Грузинская", photo: "",
    time: 90, difficulty: 3, baseServings: 4, tags: ["тесто", "мясо", "пряное"],
    ingredients: [
      { name: "Мука", qty: 500, unit: "г", group: "Бакалея", staple: true },
      { name: "Фарш говяжий", qty: 400, unit: "г", group: "Мясо", staple: false },
      { name: "Фарш свиной", qty: 200, unit: "г", group: "Мясо", staple: false },
      { name: "Лук", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Кинза", qty: 1, unit: "пучок", group: "Овощи", staple: false },
      { name: "Зира", qty: 1, unit: "ч.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Замесите крутое тесто, дайте отдохнуть 30 минут.", timer: 1800 },
      { text: "Смешайте фарш с луком, кинзой, специями и водой до сочности." },
      { text: "Слепите мешочки со складками, варите 12 минут.", timer: 720 }
    ], notes: ""
  },
  {
    id: "lobio", title: "Лобио", forKid: false,
    category: "Основное", cuisine: "Грузинская", photo: "",
    time: 60, difficulty: 1, baseServings: 4, tags: ["фасоль", "веган", "пряное"],
    ingredients: [
      { name: "Красная фасоль", qty: 400, unit: "г", group: "Бакалея", staple: false },
      { name: "Лук", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Грецкие орехи", qty: 100, unit: "г", group: "Бакалея", staple: false },
      { name: "Кинза", qty: 1, unit: "пучок", group: "Овощи", staple: false },
      { name: "Хмели-сунели", qty: 1, unit: "ст.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Отварите замоченную фасоль до мягкости, 50 минут.", timer: 3000 },
      { text: "Обжарьте лук, добавьте к фасоли, часть разомните." },
      { text: "Вмешайте толчёные орехи, кинзу и специи, прогрейте." }
    ], notes: ""
  },
  {
    id: "chakhokhbili", title: "Чахохбили", forKid: false,
    category: "Основное", cuisine: "Грузинская", photo: "",
    time: 60, difficulty: 2, baseServings: 4, tags: ["курица", "тушёное", "пряное"],
    ingredients: [
      { name: "Курица", qty: 1, unit: "кг", group: "Мясо", staple: false },
      { name: "Помидоры", qty: 4, unit: "шт", group: "Овощи", staple: false },
      { name: "Лук", qty: 3, unit: "шт", group: "Овощи", staple: false },
      { name: "Кинза", qty: 1, unit: "пучок", group: "Овощи", staple: false },
      { name: "Чеснок", qty: 3, unit: "зубчика", group: "Овощи", staple: false },
      { name: "Хмели-сунели", qty: 1, unit: "ст.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Обжарьте куски курицы без масла до золотистого." },
      { text: "Добавьте лук, затем тёртые помидоры, тушите 30 минут.", timer: 1800 },
      { text: "Заправьте чесноком, кинзой и специями, дайте настояться." }
    ], notes: ""
  },

  /* ===================== Японская ===================== */
  {
    id: "ramen-shoyu", title: "Рамен сёю", forKid: false,
    category: "Суп", cuisine: "Японская", photo: "",
    time: 45, difficulty: 2, baseServings: 2, tags: ["суп", "лапша", "сытное"],
    ingredients: [
      { name: "Лапша рамен", qty: 200, unit: "г", group: "Бакалея", staple: false },
      { name: "Куриный бульон", qty: 1, unit: "л", group: "Бакалея", staple: true },
      { name: "Соевый соус", qty: 4, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Яйцо", qty: 2, unit: "шт", group: "Молочное", staple: false },
      { name: "Свинина чашу", qty: 200, unit: "г", group: "Мясо", staple: false },
      { name: "Зелёный лук", qty: 2, unit: "стебля", group: "Овощи", staple: false },
      { name: "Нори", qty: 2, unit: "листа", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Сварите яйца всмятку 6,5 минут, остудите.", timer: 390 },
      { text: "Прогрейте бульон с соевым соусом." },
      { text: "Отварите лапшу 3 минуты, разложите по мискам.", timer: 180 },
      { text: "Залейте бульоном, добавьте свинину, яйцо, лук и нори." }
    ], notes: ""
  },
  {
    id: "chicken-teriyaki", title: "Курица терияки", forKid: true,
    category: "Основное", cuisine: "Японская", photo: "",
    time: 25, difficulty: 1, baseServings: 2, tags: ["курица", "быстро", "детское"],
    ingredients: [
      { name: "Куриное филе", qty: 400, unit: "г", group: "Мясо", staple: false },
      { name: "Соевый соус", qty: 4, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Мирин", qty: 2, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Сахар", qty: 1, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Кунжут", qty: 1, unit: "ст.л.", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Обжарьте филе до золотистого, 6 минут.", timer: 360 },
      { text: "Влейте соус из сои, мирина и сахара, выпарьте до глянца." },
      { text: "Посыпьте кунжутом, подавайте с рисом." }
    ], notes: ""
  },
  {
    id: "miso-soup", title: "Суп мисо", forKid: false,
    category: "Суп", cuisine: "Японская", photo: "",
    time: 15, difficulty: 1, baseServings: 2, tags: ["суп", "быстро", "веган"],
    ingredients: [
      { name: "Паста мисо", qty: 3, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Тофу", qty: 150, unit: "г", group: "Бакалея", staple: false },
      { name: "Вакаме", qty: 5, unit: "г", group: "Бакалея", staple: false },
      { name: "Даси или овощной бульон", qty: 800, unit: "мл", group: "Бакалея", staple: true },
      { name: "Зелёный лук", qty: 1, unit: "стебель", group: "Овощи", staple: false }
    ],
    steps: [
      { text: "Нагрейте даси, не доводя до кипения." },
      { text: "Разведите мисо в половнике бульона, верните в кастрюлю." },
      { text: "Добавьте тофу кубиком и вакаме, прогрейте, посыпьте луком." }
    ], notes: ""
  },
  {
    id: "gyudon", title: "Гюдон (рис с говядиной)", forKid: true,
    category: "Основное", cuisine: "Японская", photo: "",
    time: 25, difficulty: 1, baseServings: 2, tags: ["рис", "говядина", "быстро"],
    ingredients: [
      { name: "Говядина тонкими ломтиками", qty: 300, unit: "г", group: "Мясо", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Соевый соус", qty: 3, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Мирин", qty: 2, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Рис", qty: 200, unit: "г", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Отварите рис." },
      { text: "Потушите лук в соусе из сои и мирина, добавьте говядину, готовьте 5 минут.", timer: 300 },
      { text: "Выложите на рис." }
    ], notes: ""
  },
  {
    id: "onigiri", title: "Онигири", forKid: true,
    category: "Закуска", cuisine: "Японская", photo: "",
    time: 20, difficulty: 1, baseServings: 3, tags: ["рис", "детское", "перекус"],
    ingredients: [
      { name: "Рис японский", qty: 300, unit: "г", group: "Бакалея", staple: true },
      { name: "Нори", qty: 3, unit: "листа", group: "Бакалея", staple: false },
      { name: "Тунец консервированный", qty: 100, unit: "г", group: "Бакалея", staple: false },
      { name: "Соль", qty: null, unit: "по вкусу", group: "Специи", staple: true }
    ],
    steps: [
      { text: "Сварите рис, слегка остудите." },
      { text: "Влажными руками сформуйте треугольники с начинкой из тунца." },
      { text: "Оберните полоской нори." }
    ], notes: ""
  },

  /* ===================== Китайская ===================== */
  {
    id: "kung-pao", title: "Курица гунбао", forKid: false,
    category: "Основное", cuisine: "Китайская", photo: "",
    time: 30, difficulty: 2, baseServings: 3, tags: ["курица", "острое", "вок"],
    ingredients: [
      { name: "Куриное филе", qty: 400, unit: "г", group: "Мясо", staple: false },
      { name: "Арахис", qty: 80, unit: "г", group: "Бакалея", staple: false },
      { name: "Перец чили сушёный", qty: 5, unit: "шт", group: "Специи", staple: false },
      { name: "Соевый соус", qty: 3, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Рисовый уксус", qty: 1, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Чеснок", qty: 3, unit: "зубчика", group: "Овощи", staple: false }
    ],
    steps: [
      { text: "Обжарьте курицу кубиком на сильном огне до корочки." },
      { text: "Добавьте чили и чеснок, затем соус из сои и уксуса." },
      { text: "Вмешайте арахис, прогрейте минуту." }
    ], notes: ""
  },
  {
    id: "fried-rice", title: "Жареный рис", forKid: true,
    category: "Основное", cuisine: "Китайская", photo: "",
    time: 20, difficulty: 1, baseServings: 3, tags: ["рис", "быстро", "детское"],
    ingredients: [
      { name: "Варёный рис", qty: 400, unit: "г", group: "Бакалея", staple: false },
      { name: "Яйцо", qty: 2, unit: "шт", group: "Молочное", staple: false },
      { name: "Морковь", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Зелёный горошек", qty: 100, unit: "г", group: "Заморозка", staple: false },
      { name: "Соевый соус", qty: 2, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Зелёный лук", qty: 2, unit: "стебля", group: "Овощи", staple: false }
    ],
    steps: [
      { text: "Обжарьте овощи на сильном огне." },
      { text: "Отодвиньте, вбейте яйца, размешайте." },
      { text: "Добавьте холодный рис и соевый соус, прогрейте, посыпьте луком." }
    ], notes: ""
  },
  {
    id: "mapo-tofu", title: "Мапо тофу", forKid: false,
    category: "Основное", cuisine: "Китайская", photo: "",
    time: 25, difficulty: 2, baseServings: 3, tags: ["тофу", "острое"],
    ingredients: [
      { name: "Тофу", qty: 400, unit: "г", group: "Бакалея", staple: false },
      { name: "Фарш свиной", qty: 150, unit: "г", group: "Мясо", staple: false },
      { name: "Паста доубаньцзян", qty: 2, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Чеснок", qty: 3, unit: "зубчика", group: "Овощи", staple: false },
      { name: "Зелёный лук", qty: 2, unit: "стебля", group: "Овощи", staple: false }
    ],
    steps: [
      { text: "Обжарьте фарш, добавьте пасту и чеснок." },
      { text: "Влейте стакан воды, выложите тофу кубиком, тушите 8 минут.", timer: 480 },
      { text: "Загустите крахмалом, посыпьте луком." }
    ], notes: ""
  },
  {
    id: "chicken-noodles", title: "Лапша вок с курицей", forKid: true,
    category: "Основное", cuisine: "Китайская", photo: "",
    time: 25, difficulty: 1, baseServings: 2, tags: ["лапша", "быстро", "детское"],
    ingredients: [
      { name: "Лапша удон или яичная", qty: 250, unit: "г", group: "Бакалея", staple: false },
      { name: "Куриное филе", qty: 300, unit: "г", group: "Мясо", staple: false },
      { name: "Болгарский перец", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Морковь", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Соевый соус", qty: 3, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Чеснок", qty: 2, unit: "зубчика", group: "Овощи", staple: false }
    ],
    steps: [
      { text: "Отварите лапшу, откиньте." },
      { text: "Обжарьте курицу и овощи соломкой на сильном огне." },
      { text: "Добавьте лапшу и соевый соус, прогрейте." }
    ], notes: ""
  },

  /* ===================== Тайская ===================== */
  {
    id: "pad-thai", title: "Пад Тай", forKid: false,
    category: "Основное", cuisine: "Тайская", photo: "",
    time: 30, difficulty: 2, baseServings: 2, tags: ["лапша", "креветки"],
    ingredients: [
      { name: "Рисовая лапша", qty: 200, unit: "г", group: "Бакалея", staple: false },
      { name: "Креветки", qty: 200, unit: "г", group: "Мясо", staple: false },
      { name: "Яйцо", qty: 2, unit: "шт", group: "Молочное", staple: false },
      { name: "Ростки сои", qty: 100, unit: "г", group: "Овощи", staple: false },
      { name: "Тамаринд паста", qty: 2, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Рыбный соус", qty: 2, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Арахис", qty: 50, unit: "г", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Замочите лапшу в тёплой воде 15 минут.", timer: 900 },
      { text: "Обжарьте креветки, отодвиньте, вбейте яйца." },
      { text: "Добавьте лапшу, соус из тамаринда и рыбного соуса, ростки, прогрейте." },
      { text: "Посыпьте дроблёным арахисом." }
    ], notes: ""
  },
  {
    id: "green-curry", title: "Зелёное карри", forKid: false,
    category: "Основное", cuisine: "Тайская", photo: "",
    time: 35, difficulty: 2, baseServings: 3, tags: ["карри", "острое", "кокос"],
    ingredients: [
      { name: "Куриное филе", qty: 400, unit: "г", group: "Мясо", staple: false },
      { name: "Паста зелёного карри", qty: 3, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Кокосовое молоко", qty: 400, unit: "мл", group: "Бакалея", staple: false },
      { name: "Баклажаны тайские", qty: 150, unit: "г", group: "Овощи", staple: false },
      { name: "Базилик", qty: 1, unit: "пучок", group: "Овощи", staple: false },
      { name: "Рыбный соус", qty: 1, unit: "ст.л.", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Прогрейте пасту карри в части кокосового молока." },
      { text: "Добавьте курицу, остальное молоко и овощи, тушите 20 минут.", timer: 1200 },
      { text: "Заправьте рыбным соусом и базиликом." }
    ], notes: ""
  },
  {
    id: "mango-sticky-rice", title: "Манго с клейким рисом", forKid: true,
    category: "Десерт", cuisine: "Тайская", photo: "",
    time: 40, difficulty: 1, baseServings: 2, tags: ["десерт", "манго", "детское"],
    ingredients: [
      { name: "Клейкий рис", qty: 200, unit: "г", group: "Бакалея", staple: false },
      { name: "Кокосовое молоко", qty: 200, unit: "мл", group: "Бакалея", staple: false },
      { name: "Манго спелое", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Сахар", qty: 3, unit: "ст.л.", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Замочите рис на 30 минут, отварите на пару 20 минут.", timer: 1200 },
      { text: "Прогрейте кокосовое молоко с сахаром, залейте рис, дайте впитаться." },
      { text: "Подавайте с дольками манго." }
    ], notes: ""
  },

  /* ===================== Мексиканская ===================== */
  {
    id: "chicken-tacos", title: "Тако с курицей", forKid: true,
    category: "Основное", cuisine: "Мексиканская", photo: "",
    time: 30, difficulty: 1, baseServings: 3, tags: ["курица", "детское"],
    ingredients: [
      { name: "Тортильи кукурузные", qty: 6, unit: "шт", group: "Бакалея", staple: false },
      { name: "Куриное филе", qty: 400, unit: "г", group: "Мясо", staple: false },
      { name: "Помидор", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Сыр чеддер", qty: 100, unit: "г", group: "Молочное", staple: false },
      { name: "Салат айсберг", qty: 0.5, unit: "кочана", group: "Овощи", staple: false },
      { name: "Паприка", qty: 1, unit: "ч.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Обжарьте курицу с паприкой, нарежьте." },
      { text: "Прогрейте тортильи." },
      { text: "Соберите тако с курицей, овощами и сыром." }
    ], notes: ""
  },
  {
    id: "chili-con-carne", title: "Чили кон карне", forKid: false,
    category: "Основное", cuisine: "Мексиканская", photo: "",
    time: 60, difficulty: 1, baseServings: 4, tags: ["фасоль", "мясо", "острое"],
    ingredients: [
      { name: "Фарш говяжий", qty: 500, unit: "г", group: "Мясо", staple: false },
      { name: "Красная фасоль", qty: 400, unit: "г", group: "Бакалея", staple: false },
      { name: "Томаты", qty: 400, unit: "г", group: "Бакалея", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Перец чили", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Зира", qty: 1, unit: "ч.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Обжарьте фарш с луком и специями." },
      { text: "Добавьте томаты и фасоль, тушите 40 минут.", timer: 2400 }
    ], notes: ""
  },
  {
    id: "quesadilla", title: "Кесадилья", forKid: true,
    category: "Закуска", cuisine: "Мексиканская", photo: "",
    time: 15, difficulty: 1, baseServings: 2, tags: ["сыр", "быстро", "детское"],
    ingredients: [
      { name: "Тортильи пшеничные", qty: 4, unit: "шт", group: "Бакалея", staple: false },
      { name: "Сыр чеддер", qty: 200, unit: "г", group: "Молочное", staple: false },
      { name: "Куриное филе варёное", qty: 150, unit: "г", group: "Мясо", staple: false },
      { name: "Болгарский перец", qty: 1, unit: "шт", group: "Овощи", staple: false }
    ],
    steps: [
      { text: "Выложите на тортилью сыр, курицу и перец, накройте второй." },
      { text: "Обжарьте на сухой сковороде по 2 минуты с каждой стороны.", timer: 120 },
      { text: "Разрежьте на сегменты." }
    ], notes: ""
  },

  /* ===================== Индийская ===================== */
  {
    id: "butter-chicken", title: "Баттер чикен", forKid: false,
    category: "Основное", cuisine: "Индийская", photo: "",
    time: 50, difficulty: 2, baseServings: 4, tags: ["курица", "карри", "сливочное"],
    ingredients: [
      { name: "Куриное филе", qty: 600, unit: "г", group: "Мясо", staple: false },
      { name: "Йогурт", qty: 150, unit: "г", group: "Молочное", staple: false },
      { name: "Томатное пюре", qty: 400, unit: "г", group: "Бакалея", staple: false },
      { name: "Сливки", qty: 150, unit: "мл", group: "Молочное", staple: false },
      { name: "Гарам масала", qty: 2, unit: "ч.л.", group: "Специи", staple: false },
      { name: "Имбирь", qty: 20, unit: "г", group: "Овощи", staple: false },
      { name: "Чеснок", qty: 3, unit: "зубчика", group: "Овощи", staple: false }
    ],
    steps: [
      { text: "Замаринуйте курицу в йогурте со специями 30 минут.", timer: 1800 },
      { text: "Обжарьте курицу, отложите." },
      { text: "Потушите томатное пюре с имбирём и чесноком, влейте сливки." },
      { text: "Верните курицу, томите 15 минут.", timer: 900 }
    ], notes: ""
  },
  {
    id: "dal-tadka", title: "Дал тадка", forKid: true,
    category: "Основное", cuisine: "Индийская", photo: "",
    time: 40, difficulty: 1, baseServings: 4, tags: ["чечевица", "веган", "сытное"],
    ingredients: [
      { name: "Красная чечевица", qty: 250, unit: "г", group: "Бакалея", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Помидор", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Куркума", qty: 1, unit: "ч.л.", group: "Специи", staple: false },
      { name: "Зира", qty: 1, unit: "ч.л.", group: "Специи", staple: false },
      { name: "Чеснок", qty: 3, unit: "зубчика", group: "Овощи", staple: false }
    ],
    steps: [
      { text: "Отварите чечевицу с куркумой до разваривания, 20 минут.", timer: 1200 },
      { text: "Сделайте тадку: обжарьте зиру, чеснок и лук, добавьте помидор." },
      { text: "Влейте тадку в чечевицу, прогрейте." }
    ], notes: ""
  },
  {
    id: "palak-paneer", title: "Палак панир", forKid: true,
    category: "Основное", cuisine: "Индийская", photo: "",
    time: 35, difficulty: 2, baseServings: 3, tags: ["шпинат", "сыр", "вегетарианское"],
    ingredients: [
      { name: "Шпинат", qty: 400, unit: "г", group: "Овощи", staple: false },
      { name: "Панир", qty: 250, unit: "г", group: "Молочное", staple: false },
      { name: "Сливки", qty: 100, unit: "мл", group: "Молочное", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Гарам масала", qty: 1, unit: "ч.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Бланшируйте шпинат, измельчите в пюре." },
      { text: "Обжарьте лук со специями, добавьте пюре и сливки." },
      { text: "Выложите кубики панира, прогрейте 5 минут.", timer: 300 }
    ], notes: ""
  },
  {
    id: "chicken-biryani", title: "Бирьяни с курицей", forKid: false,
    category: "Основное", cuisine: "Индийская", photo: "",
    time: 70, difficulty: 3, baseServings: 4, tags: ["рис", "курица", "праздничное"],
    ingredients: [
      { name: "Рис басмати", qty: 400, unit: "г", group: "Бакалея", staple: false },
      { name: "Куриные бёдра", qty: 600, unit: "г", group: "Мясо", staple: false },
      { name: "Йогурт", qty: 150, unit: "г", group: "Молочное", staple: false },
      { name: "Лук", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Шафран", qty: 1, unit: "щепотка", group: "Специи", staple: false },
      { name: "Гарам масала", qty: 2, unit: "ч.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Замаринуйте курицу в йогурте со специями 30 минут.", timer: 1800 },
      { text: "Отварите рис до полуготовности." },
      { text: "Выложите слоями курицу и рис, томите под крышкой 25 минут.", timer: 1500 }
    ], notes: ""
  },

  /* ===================== Французская ===================== */
  {
    id: "ratatouille", title: "Рататуй", forKid: true,
    category: "Основное", cuisine: "Французская", photo: "",
    time: 60, difficulty: 2, baseServings: 4, tags: ["овощи", "веган", "запечённое"],
    ingredients: [
      { name: "Баклажан", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Кабачок", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Помидоры", qty: 4, unit: "шт", group: "Овощи", staple: false },
      { name: "Болгарский перец", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Прованские травы", qty: 1, unit: "ст.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Сделайте соус из лука, перца и части помидоров." },
      { text: "Выложите соус, сверху кружки овощей внахлёст." },
      { text: "Запекайте под фольгой при 180° 40 минут.", timer: 2400 }
    ], notes: ""
  },
  {
    id: "quiche-lorraine", title: "Киш лорен", forKid: false,
    category: "Выпечка", cuisine: "Французская", photo: "",
    time: 70, difficulty: 2, baseServings: 6, tags: ["пирог", "бекон", "сыр"],
    ingredients: [
      { name: "Слоёное тесто", qty: 250, unit: "г", group: "Заморозка", staple: false },
      { name: "Бекон", qty: 200, unit: "г", group: "Мясо", staple: false },
      { name: "Сливки", qty: 200, unit: "мл", group: "Молочное", staple: false },
      { name: "Яйцо", qty: 3, unit: "шт", group: "Молочное", staple: false },
      { name: "Сыр грюйер", qty: 100, unit: "г", group: "Молочное", staple: false }
    ],
    steps: [
      { text: "Выложите тесто в форму, обжарьте бекон." },
      { text: "Смешайте яйца со сливками и сыром, добавьте бекон." },
      { text: "Залейте основу, выпекайте при 180° 35 минут.", timer: 2100 }
    ], notes: ""
  },
  {
    id: "soupe-a-l-oignon", title: "Луковый суп", forKid: false,
    category: "Суп", cuisine: "Французская", photo: "",
    time: 60, difficulty: 2, baseServings: 4, tags: ["суп", "лук", "сыр"],
    ingredients: [
      { name: "Лук", qty: 6, unit: "шт", group: "Овощи", staple: false },
      { name: "Говяжий бульон", qty: 1.5, unit: "л", group: "Бакалея", staple: true },
      { name: "Сыр грюйер", qty: 150, unit: "г", group: "Молочное", staple: false },
      { name: "Багет", qty: 0.5, unit: "шт", group: "Бакалея", staple: false },
      { name: "Сливочное масло", qty: 50, unit: "г", group: "Молочное", staple: false }
    ],
    steps: [
      { text: "Карамелизуйте лук на масле 30 минут до золотисто-коричневого.", timer: 1800 },
      { text: "Влейте бульон, томите 15 минут.", timer: 900 },
      { text: "Разлейте, накройте гренкой с сыром, запеките под грилем 5 минут.", timer: 300 }
    ], notes: ""
  },
  {
    id: "crepes", title: "Французские крепы", forKid: true,
    category: "Завтрак", cuisine: "Французская", photo: "",
    time: 30, difficulty: 1, baseServings: 4, tags: ["детское", "сладкое", "завтрак"],
    ingredients: [
      { name: "Мука", qty: 200, unit: "г", group: "Бакалея", staple: true },
      { name: "Молоко", qty: 500, unit: "мл", group: "Молочное", staple: false },
      { name: "Яйцо", qty: 3, unit: "шт", group: "Молочное", staple: false },
      { name: "Сливочное масло", qty: 30, unit: "г", group: "Молочное", staple: false },
      { name: "Сахар", qty: 1, unit: "ст.л.", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Взбейте яйца, молоко, муку и сахар до гладкости, дайте постоять 15 минут.", timer: 900 },
      { text: "Жарьте тонкие блинчики на сливочном масле по 1 минуте.", timer: 60 }
    ], notes: ""
  },

  /* ===================== Корейская ===================== */
  {
    id: "bibimbap", title: "Пибимпап", forKid: false,
    category: "Основное", cuisine: "Корейская", photo: "",
    time: 40, difficulty: 2, baseServings: 2, tags: ["рис", "овощи", "яйцо"],
    ingredients: [
      { name: "Рис", qty: 300, unit: "г", group: "Бакалея", staple: true },
      { name: "Говядина", qty: 200, unit: "г", group: "Мясо", staple: false },
      { name: "Шпинат", qty: 100, unit: "г", group: "Овощи", staple: false },
      { name: "Морковь", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Яйцо", qty: 2, unit: "шт", group: "Молочное", staple: false },
      { name: "Паста кочудян", qty: 2, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Кунжутное масло", qty: 1, unit: "ст.л.", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Отварите рис. Обжарьте говядину и овощи по отдельности." },
      { text: "Выложите рис, сверху овощи веером, говядину и яичницу-глазунью." },
      { text: "Подавайте с кочудяном и кунжутным маслом." }
    ], notes: ""
  },
  {
    id: "bulgogi", title: "Пулькоги", forKid: true,
    category: "Основное", cuisine: "Корейская", photo: "",
    time: 30, difficulty: 1, baseServings: 3, tags: ["говядина", "маринад"],
    ingredients: [
      { name: "Говядина тонко", qty: 500, unit: "г", group: "Мясо", staple: false },
      { name: "Соевый соус", qty: 4, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Груша", qty: 0.5, unit: "шт", group: "Овощи", staple: false },
      { name: "Чеснок", qty: 3, unit: "зубчика", group: "Овощи", staple: false },
      { name: "Сахар", qty: 1, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Кунжутное масло", qty: 1, unit: "ст.л.", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Замаринуйте говядину в соусе из сои, тёртой груши, чеснока и сахара 20 минут.", timer: 1200 },
      { text: "Обжарьте на сильном огне 5 минут.", timer: 300 }
    ], notes: ""
  },
  {
    id: "kimchi-jjigae", title: "Кимчи чигэ", forKid: false,
    category: "Суп", cuisine: "Корейская", photo: "",
    time: 35, difficulty: 1, baseServings: 3, tags: ["суп", "острое", "кимчи"],
    ingredients: [
      { name: "Кимчи", qty: 300, unit: "г", group: "Овощи", staple: false },
      { name: "Свинина", qty: 200, unit: "г", group: "Мясо", staple: false },
      { name: "Тофу", qty: 200, unit: "г", group: "Бакалея", staple: false },
      { name: "Зелёный лук", qty: 2, unit: "стебля", group: "Овощи", staple: false },
      { name: "Паста кочудян", qty: 1, unit: "ст.л.", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Обжарьте свинину с кимчи 5 минут.", timer: 300 },
      { text: "Влейте воду, добавьте пасту, варите 15 минут.", timer: 900 },
      { text: "Выложите тофу и лук, прогрейте." }
    ], notes: ""
  },

  /* ===================== Ближневосточная ===================== */
  {
    id: "hummus", title: "Хумус", forKid: true,
    category: "Закуска", cuisine: "Ближневосточная", photo: "",
    time: 15, difficulty: 1, baseServings: 4, tags: ["нут", "веган", "соус"],
    ingredients: [
      { name: "Нут варёный", qty: 400, unit: "г", group: "Бакалея", staple: false },
      { name: "Тахини", qty: 3, unit: "ст.л.", group: "Бакалея", staple: false },
      { name: "Лимон", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Чеснок", qty: 2, unit: "зубчика", group: "Овощи", staple: false },
      { name: "Оливковое масло", qty: 3, unit: "ст.л.", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Пробейте нут блендером с тахини, соком лимона и чесноком." },
      { text: "Доведите до кремовости ледяной водой, посолите." },
      { text: "Полейте оливковым маслом." }
    ], notes: ""
  },
  {
    id: "falafel", title: "Фалафель", forKid: true,
    category: "Закуска", cuisine: "Ближневосточная", photo: "",
    time: 40, difficulty: 2, baseServings: 4, tags: ["нут", "веган", "жареное"],
    ingredients: [
      { name: "Нут сухой", qty: 250, unit: "г", group: "Бакалея", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Чеснок", qty: 3, unit: "зубчика", group: "Овощи", staple: false },
      { name: "Кинза", qty: 1, unit: "пучок", group: "Овощи", staple: false },
      { name: "Зира", qty: 1, unit: "ч.л.", group: "Специи", staple: false },
      { name: "Масло для фритюра", qty: null, unit: "для жарки", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Замочите нут на ночь (сырой!), измельчите с луком, чесноком и зеленью." },
      { text: "Сформуйте шарики, дайте постоять 20 минут.", timer: 1200 },
      { text: "Обжарьте во фритюре до золотистого, 4 минуты.", timer: 240 }
    ], notes: ""
  },
  {
    id: "shakshuka", title: "Шакшука", forKid: true,
    category: "Завтрак", cuisine: "Ближневосточная", photo: "",
    time: 25, difficulty: 1, baseServings: 2, tags: ["яйцо", "завтрак", "томаты"],
    ingredients: [
      { name: "Яйцо", qty: 4, unit: "шт", group: "Молочное", staple: false },
      { name: "Помидоры", qty: 4, unit: "шт", group: "Овощи", staple: false },
      { name: "Болгарский перец", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Паприка", qty: 1, unit: "ч.л.", group: "Специи", staple: false },
      { name: "Зира", qty: 0.5, unit: "ч.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Потушите лук, перец и помидоры со специями 10 минут.", timer: 600 },
      { text: "Сделайте углубления, влейте яйца, накройте, готовьте 6 минут.", timer: 360 }
    ], notes: ""
  },
  {
    id: "tabbouleh", title: "Табуле", forKid: false,
    category: "Салат", cuisine: "Ближневосточная", photo: "",
    time: 20, difficulty: 1, baseServings: 4, tags: ["салат", "веган", "зелень"],
    ingredients: [
      { name: "Булгур", qty: 100, unit: "г", group: "Бакалея", staple: false },
      { name: "Петрушка", qty: 2, unit: "пучка", group: "Овощи", staple: false },
      { name: "Мята", qty: 1, unit: "пучок", group: "Овощи", staple: false },
      { name: "Помидоры", qty: 3, unit: "шт", group: "Овощи", staple: false },
      { name: "Лимон", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Оливковое масло", qty: 3, unit: "ст.л.", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Запарьте булгур кипятком, дайте набухнуть 15 минут.", timer: 900 },
      { text: "Мелко порубите зелень и помидоры." },
      { text: "Смешайте всё с соком лимона и маслом." }
    ], notes: ""
  },

  /* ===================== Греческая ===================== */
  {
    id: "greek-salad", title: "Греческий салат", forKid: true,
    category: "Салат", cuisine: "Греческая", photo: "",
    time: 15, difficulty: 1, baseServings: 3, tags: ["салат", "быстро", "сыр"],
    ingredients: [
      { name: "Помидоры", qty: 3, unit: "шт", group: "Овощи", staple: false },
      { name: "Огурец", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Фета", qty: 200, unit: "г", group: "Молочное", staple: false },
      { name: "Маслины", qty: 100, unit: "г", group: "Бакалея", staple: false },
      { name: "Красный лук", qty: 0.5, unit: "шт", group: "Овощи", staple: false },
      { name: "Оливковое масло", qty: 3, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Орегано", qty: 1, unit: "ч.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Нарежьте овощи крупно, добавьте маслины." },
      { text: "Сверху положите кусок феты, полейте маслом, посыпьте орегано." }
    ], notes: ""
  },
  {
    id: "moussaka", title: "Мусака", forKid: false,
    category: "Основное", cuisine: "Греческая", photo: "",
    time: 90, difficulty: 3, baseServings: 6, tags: ["запеканка", "баклажан", "мясо"],
    ingredients: [
      { name: "Баклажаны", qty: 3, unit: "шт", group: "Овощи", staple: false },
      { name: "Фарш бараний или говяжий", qty: 500, unit: "г", group: "Мясо", staple: false },
      { name: "Томаты", qty: 400, unit: "г", group: "Бакалея", staple: false },
      { name: "Молоко", qty: 500, unit: "мл", group: "Молочное", staple: false },
      { name: "Сливочное масло", qty: 50, unit: "г", group: "Молочное", staple: false },
      { name: "Мука", qty: 50, unit: "г", group: "Бакалея", staple: true },
      { name: "Сыр", qty: 100, unit: "г", group: "Молочное", staple: false }
    ],
    steps: [
      { text: "Обжарьте ломтики баклажанов." },
      { text: "Потушите фарш с томатами 20 минут.", timer: 1200 },
      { text: "Сварите бешамель. Соберите слои, запекайте при 180° 40 минут.", timer: 2400 }
    ], notes: ""
  },
  {
    id: "souvlaki", title: "Сувлаки", forKid: true,
    category: "Основное", cuisine: "Греческая", photo: "",
    time: 35, difficulty: 1, baseServings: 3, tags: ["курица", "гриль", "шашлычки"],
    ingredients: [
      { name: "Куриное филе", qty: 600, unit: "г", group: "Мясо", staple: false },
      { name: "Лимон", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Оливковое масло", qty: 3, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Чеснок", qty: 2, unit: "зубчика", group: "Овощи", staple: false },
      { name: "Орегано", qty: 1, unit: "ч.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Замаринуйте кубики курицы в масле, лимоне, чесноке и орегано 20 минут.", timer: 1200 },
      { text: "Нанижите на шпажки, обжарьте на гриле по 4 минуты с каждой стороны.", timer: 240 }
    ], notes: ""
  },

  /* ===================== Испанская ===================== */
  {
    id: "paella", title: "Паэлья с морепродуктами", forKid: false,
    category: "Основное", cuisine: "Испанская", photo: "",
    time: 50, difficulty: 3, baseServings: 4, tags: ["рис", "морепродукты", "праздничное"],
    ingredients: [
      { name: "Рис круглозёрный", qty: 350, unit: "г", group: "Бакалея", staple: false },
      { name: "Морепродукты коктейль", qty: 400, unit: "г", group: "Заморозка", staple: false },
      { name: "Куриное бедро", qty: 300, unit: "г", group: "Мясо", staple: false },
      { name: "Шафран", qty: 1, unit: "щепотка", group: "Специи", staple: false },
      { name: "Болгарский перец", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Зелёный горошек", qty: 100, unit: "г", group: "Заморозка", staple: false },
      { name: "Бульон", qty: 800, unit: "мл", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Обжарьте курицу и перец на широкой сковороде." },
      { text: "Всыпьте рис, влейте бульон с шафраном, не мешайте, готовьте 18 минут.", timer: 1080 },
      { text: "Выложите морепродукты и горошек, доведите до готовности." }
    ], notes: ""
  },
  {
    id: "tortilla-espanola", title: "Испанская тортилья", forKid: true,
    category: "Завтрак", cuisine: "Испанская", photo: "",
    time: 35, difficulty: 2, baseServings: 4, tags: ["яйцо", "картофель", "завтрак"],
    ingredients: [
      { name: "Картофель", qty: 500, unit: "г", group: "Овощи", staple: false },
      { name: "Яйцо", qty: 6, unit: "шт", group: "Молочное", staple: false },
      { name: "Лук", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Оливковое масло", qty: 4, unit: "ст.л.", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Томите ломтики картофеля с луком в масле 15 минут до мягкости.", timer: 900 },
      { text: "Смешайте с взбитыми яйцами, вылейте на сковороду." },
      { text: "Жарьте, переверните тарелкой, доведите вторую сторону, 8 минут.", timer: 480 }
    ], notes: ""
  },
  {
    id: "gazpacho", title: "Гаспачо", forKid: false,
    category: "Суп", cuisine: "Испанская", photo: "",
    time: 15, difficulty: 1, baseServings: 4, tags: ["суп", "холодный", "веган"],
    ingredients: [
      { name: "Помидоры спелые", qty: 800, unit: "г", group: "Овощи", staple: false },
      { name: "Огурец", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Болгарский перец", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Чеснок", qty: 1, unit: "зубчик", group: "Овощи", staple: false },
      { name: "Оливковое масло", qty: 3, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Хлеб", qty: 50, unit: "г", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Пробейте все овощи блендером с хлебом и маслом." },
      { text: "Посолите, охладите в холодильнике 2 часа." }
    ], notes: ""
  },

  /* ===================== Вьетнамская ===================== */
  {
    id: "pho-bo", title: "Фо бо", forKid: false,
    category: "Суп", cuisine: "Вьетнамская", photo: "",
    time: 120, difficulty: 3, baseServings: 4, tags: ["суп", "говядина", "лапша"],
    ingredients: [
      { name: "Говяжьи кости", qty: 1, unit: "кг", group: "Мясо", staple: false },
      { name: "Говяжья вырезка", qty: 300, unit: "г", group: "Мясо", staple: false },
      { name: "Рисовая лапша", qty: 250, unit: "г", group: "Бакалея", staple: false },
      { name: "Имбирь", qty: 30, unit: "г", group: "Овощи", staple: false },
      { name: "Бадьян", qty: 3, unit: "звёздочки", group: "Специи", staple: false },
      { name: "Корица", qty: 1, unit: "палочка", group: "Специи", staple: false },
      { name: "Зелёный лук", qty: 3, unit: "стебля", group: "Овощи", staple: false }
    ],
    steps: [
      { text: "Варите кости с обожжённым имбирём и специями 90 минут.", timer: 5400 },
      { text: "Отварите лапшу, разложите по мискам с тонкой сырой вырезкой." },
      { text: "Залейте кипящим бульоном, посыпьте луком и зеленью." }
    ], notes: ""
  },
  {
    id: "nem-spring-rolls", title: "Спринг-роллы немы", forKid: true,
    category: "Закуска", cuisine: "Вьетнамская", photo: "",
    time: 40, difficulty: 2, baseServings: 4, tags: ["закуска", "жареное"],
    ingredients: [
      { name: "Рисовая бумага", qty: 12, unit: "листов", group: "Бакалея", staple: false },
      { name: "Фарш свиной", qty: 250, unit: "г", group: "Мясо", staple: false },
      { name: "Морковь", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Стеклянная лапша", qty: 50, unit: "г", group: "Бакалея", staple: false },
      { name: "Грибы древесные", qty: 20, unit: "г", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Смешайте фарш с тёртой морковью, размоченной лапшой и грибами." },
      { text: "Заверните в смоченную рисовую бумагу." },
      { text: "Обжарьте до хруста, 5 минут.", timer: 300 }
    ], notes: ""
  },
  {
    id: "banh-mi", title: "Бань ми", forKid: true,
    category: "Закуска", cuisine: "Вьетнамская", photo: "",
    time: 25, difficulty: 1, baseServings: 2, tags: ["сэндвич", "быстро"],
    ingredients: [
      { name: "Багет", qty: 2, unit: "шт", group: "Бакалея", staple: false },
      { name: "Свинина или паштет", qty: 200, unit: "г", group: "Мясо", staple: false },
      { name: "Морковь", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Дайкон", qty: 100, unit: "г", group: "Овощи", staple: false },
      { name: "Кинза", qty: 1, unit: "пучок", group: "Овощи", staple: false },
      { name: "Рисовый уксус", qty: 2, unit: "ст.л.", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Замаринуйте морковь и дайкон в уксусе с сахаром 15 минут.", timer: 900 },
      { text: "Наполните багет мясом, маринованными овощами и кинзой." }
    ], notes: ""
  },

  /* ===================== Узбекская ===================== */
  {
    id: "plov", title: "Плов", forKid: true,
    category: "Основное", cuisine: "Узбекская", photo: "",
    time: 90, difficulty: 2, baseServings: 6, tags: ["рис", "баранина", "сытное"],
    ingredients: [
      { name: "Рис девзира", qty: 500, unit: "г", group: "Бакалея", staple: false },
      { name: "Баранина", qty: 500, unit: "г", group: "Мясо", staple: false },
      { name: "Морковь", qty: 500, unit: "г", group: "Овощи", staple: false },
      { name: "Лук", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Чеснок", qty: 2, unit: "головки", group: "Овощи", staple: false },
      { name: "Зира", qty: 1, unit: "ст.л.", group: "Специи", staple: false },
      { name: "Растительное масло", qty: 150, unit: "мл", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Раскалите масло, обжарьте мясо, затем лук и морковь соломкой." },
      { text: "Залейте водой, добавьте зиру и чеснок, томите зирвак 30 минут.", timer: 1800 },
      { text: "Всыпьте промытый рис, готовьте под крышкой 25 минут.", timer: 1500 }
    ], notes: ""
  },
  {
    id: "lagman", title: "Лагман", forKid: false,
    category: "Суп", cuisine: "Узбекская", photo: "",
    time: 75, difficulty: 2, baseServings: 4, tags: ["суп", "лапша", "говядина"],
    ingredients: [
      { name: "Говядина", qty: 400, unit: "г", group: "Мясо", staple: false },
      { name: "Лапша лагманная", qty: 400, unit: "г", group: "Бакалея", staple: false },
      { name: "Болгарский перец", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Помидоры", qty: 3, unit: "шт", group: "Овощи", staple: false },
      { name: "Редька", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Чеснок", qty: 4, unit: "зубчика", group: "Овощи", staple: false }
    ],
    steps: [
      { text: "Обжарьте говядину, добавьте овощи и томаты, тушите 30 минут.", timer: 1800 },
      { text: "Влейте воду, доведите ваджу до готовности." },
      { text: "Отварите лапшу, залейте подливой." }
    ], notes: ""
  },
  {
    id: "samsa", title: "Самса", forKid: true,
    category: "Выпечка", cuisine: "Узбекская", photo: "",
    time: 80, difficulty: 2, baseServings: 6, tags: ["выпечка", "мясо"],
    ingredients: [
      { name: "Слоёное тесто", qty: 500, unit: "г", group: "Заморозка", staple: false },
      { name: "Баранина или говядина", qty: 400, unit: "г", group: "Мясо", staple: false },
      { name: "Лук", qty: 3, unit: "шт", group: "Овощи", staple: false },
      { name: "Курдючный жир", qty: 50, unit: "г", group: "Мясо", staple: false },
      { name: "Зира", qty: 1, unit: "ч.л.", group: "Специи", staple: false },
      { name: "Яйцо", qty: 1, unit: "шт", group: "Молочное", staple: false }
    ],
    steps: [
      { text: "Смешайте рубленое мясо с большим количеством лука, жиром и зирой." },
      { text: "Заверните начинку в тесто треугольниками, смажьте яйцом." },
      { text: "Выпекайте при 200° 35 минут.", timer: 2100 }
    ], notes: ""
  },

  /* ===================== Турецкая ===================== */
  {
    id: "menemen", title: "Мене мен", forKid: true,
    category: "Завтрак", cuisine: "Турецкая", photo: "",
    time: 20, difficulty: 1, baseServings: 2, tags: ["яйцо", "завтрак", "быстро"],
    ingredients: [
      { name: "Яйцо", qty: 4, unit: "шт", group: "Молочное", staple: false },
      { name: "Помидоры", qty: 3, unit: "шт", group: "Овощи", staple: false },
      { name: "Зелёный перец", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Сливочное масло", qty: 20, unit: "г", group: "Молочное", staple: false },
      { name: "Паприка", qty: 1, unit: "ч.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Потушите перец и помидоры на масле 8 минут.", timer: 480 },
      { text: "Влейте слегка взбитые яйца, готовьте, помешивая, до мягкого схватывания." }
    ], notes: ""
  },
  {
    id: "lahmacun", title: "Лахмаджун", forKid: false,
    category: "Выпечка", cuisine: "Турецкая", photo: "",
    time: 50, difficulty: 2, baseServings: 4, tags: ["лепёшка", "мясо"],
    ingredients: [
      { name: "Мука", qty: 300, unit: "г", group: "Бакалея", staple: true },
      { name: "Фарш бараний", qty: 300, unit: "г", group: "Мясо", staple: false },
      { name: "Помидор", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Болгарский перец", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Петрушка", qty: 1, unit: "пучок", group: "Овощи", staple: false },
      { name: "Паприка", qty: 1, unit: "ч.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Замесите тонкое тесто, дайте отдохнуть 30 минут.", timer: 1800 },
      { text: "Пробейте начинку из фарша, овощей и специй." },
      { text: "Намажьте тонко на лепёшки, выпекайте при 250° 8 минут.", timer: 480 }
    ], notes: ""
  },

  /* ===================== Марокканская ===================== */
  {
    id: "harira", title: "Харира", forKid: false,
    category: "Суп", cuisine: "Марокканская", photo: "",
    time: 70, difficulty: 2, baseServings: 6, tags: ["суп", "нут", "пряное"],
    ingredients: [
      { name: "Баранина", qty: 300, unit: "г", group: "Мясо", staple: false },
      { name: "Нут", qty: 150, unit: "г", group: "Бакалея", staple: false },
      { name: "Чечевица", qty: 100, unit: "г", group: "Бакалея", staple: false },
      { name: "Томаты", qty: 400, unit: "г", group: "Бакалея", staple: false },
      { name: "Кинза", qty: 1, unit: "пучок", group: "Овощи", staple: false },
      { name: "Имбирь молотый", qty: 1, unit: "ч.л.", group: "Специи", staple: false },
      { name: "Куркума", qty: 1, unit: "ч.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Потушите баранину со специями и томатами." },
      { text: "Добавьте нут, чечевицу и воду, варите 50 минут.", timer: 3000 },
      { text: "Заправьте зеленью, при желании загустите мукой." }
    ], notes: ""
  },
  {
    id: "couscous-ovoshi", title: "Кускус с овощами", forKid: true,
    category: "Гарнир", cuisine: "Марокканская", photo: "",
    time: 35, difficulty: 1, baseServings: 4, tags: ["кускус", "овощи", "веган"],
    ingredients: [
      { name: "Кускус", qty: 300, unit: "г", group: "Бакалея", staple: false },
      { name: "Кабачок", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Морковь", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Нут варёный", qty: 200, unit: "г", group: "Бакалея", staple: false },
      { name: "Рас-эль-ханут", qty: 1, unit: "ст.л.", group: "Специи", staple: false },
      { name: "Изюм", qty: 50, unit: "г", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Потушите овощи со специями и нутом 15 минут.", timer: 900 },
      { text: "Запарьте кускус кипятком, дайте набухнуть 5 минут, распушите вилкой.", timer: 300 },
      { text: "Соедините кускус с овощами и изюмом." }
    ], notes: ""
  },

  /* ===================== Американская ===================== */
  {
    id: "pancakes", title: "Панкейки", forKid: true,
    category: "Завтрак", cuisine: "Американская", photo: "",
    time: 25, difficulty: 1, baseServings: 3, tags: ["детское", "сладкое", "завтрак"],
    ingredients: [
      { name: "Мука", qty: 250, unit: "г", group: "Бакалея", staple: true },
      { name: "Молоко", qty: 300, unit: "мл", group: "Молочное", staple: false },
      { name: "Яйцо", qty: 2, unit: "шт", group: "Молочное", staple: false },
      { name: "Разрыхлитель", qty: 2, unit: "ч.л.", group: "Бакалея", staple: false },
      { name: "Сахар", qty: 2, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Сливочное масло", qty: 30, unit: "г", group: "Молочное", staple: false }
    ],
    steps: [
      { text: "Смешайте сухие и влажные ингредиенты отдельно, затем соедините, не перемешивая до гладкости." },
      { text: "Жарьте на сухой сковороде до пузырьков, переверните, 2 минуты.", timer: 120 },
      { text: "Подавайте с кленовым сиропом." }
    ], notes: ""
  },
  {
    id: "mac-and-cheese", title: "Макароны с сыром", forKid: true,
    category: "Основное", cuisine: "Американская", photo: "",
    time: 30, difficulty: 1, baseServings: 4, tags: ["детское", "сыр", "паста"],
    ingredients: [
      { name: "Макароны", qty: 300, unit: "г", group: "Бакалея", staple: true },
      { name: "Сыр чеддер", qty: 250, unit: "г", group: "Молочное", staple: false },
      { name: "Молоко", qty: 400, unit: "мл", group: "Молочное", staple: false },
      { name: "Сливочное масло", qty: 40, unit: "г", group: "Молочное", staple: false },
      { name: "Мука", qty: 30, unit: "г", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Отварите макароны." },
      { text: "Сварите соус: масло + мука + молоко, расплавьте сыр." },
      { text: "Смешайте с макаронами, при желании запеките 10 минут.", timer: 600 }
    ], notes: ""
  },
  {
    id: "cheeseburger", title: "Чизбургер", forKid: true,
    category: "Основное", cuisine: "Американская", photo: "",
    time: 25, difficulty: 1, baseServings: 2, tags: ["говядина", "детское"],
    ingredients: [
      { name: "Булочки для бургера", qty: 2, unit: "шт", group: "Бакалея", staple: false },
      { name: "Фарш говяжий", qty: 300, unit: "г", group: "Мясо", staple: false },
      { name: "Сыр чеддер", qty: 2, unit: "ломтика", group: "Молочное", staple: false },
      { name: "Помидор", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Салат", qty: 4, unit: "листа", group: "Овощи", staple: false },
      { name: "Соленья", qty: 1, unit: "шт", group: "Овощи", staple: false }
    ],
    steps: [
      { text: "Сформуйте котлеты, посолите, обжарьте по 3 минуты с каждой стороны.", timer: 180 },
      { text: "Положите сыр, дайте расплавиться." },
      { text: "Соберите бургер с овощами на поджаренной булочке." }
    ], notes: ""
  },
  {
    id: "caesar-salad", title: "Салат Цезарь", forKid: false,
    category: "Салат", cuisine: "Американская", photo: "",
    time: 25, difficulty: 1, baseServings: 2, tags: ["салат", "курица"],
    ingredients: [
      { name: "Салат романо", qty: 1, unit: "кочан", group: "Овощи", staple: false },
      { name: "Куриное филе", qty: 250, unit: "г", group: "Мясо", staple: false },
      { name: "Пармезан", qty: 50, unit: "г", group: "Молочное", staple: false },
      { name: "Хлеб для гренок", qty: 100, unit: "г", group: "Бакалея", staple: false },
      { name: "Соус цезарь", qty: 80, unit: "г", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Обжарьте курицу, нарежьте. Подсушите гренки." },
      { text: "Порвите салат, смешайте с соусом, курицей и гренками." },
      { text: "Посыпьте пармезаном." }
    ], notes: ""
  },

  /* ===================== Напитки ===================== */
  {
    id: "kompot", title: "Компот из сухофруктов", forKid: true,
    category: "Напиток", cuisine: "Русская", photo: "",
    time: 30, difficulty: 1, baseServings: 6, tags: ["детское", "напиток"],
    ingredients: [
      { name: "Сухофрукты ассорти", qty: 300, unit: "г", group: "Бакалея", staple: false },
      { name: "Сахар", qty: 100, unit: "г", group: "Бакалея", staple: true },
      { name: "Вода", qty: 2, unit: "л", group: "Прочее", staple: true }
    ],
    steps: [
      { text: "Промойте сухофрукты, залейте водой." },
      { text: "Доведите до кипения, добавьте сахар, варите 20 минут.", timer: 1200 },
      { text: "Дайте настояться под крышкой." }
    ], notes: ""
  },
  {
    id: "lemonade", title: "Домашний лимонад", forKid: true,
    category: "Напиток", cuisine: "Американская", photo: "",
    time: 15, difficulty: 1, baseServings: 4, tags: ["детское", "освежающий"],
    ingredients: [
      { name: "Лимоны", qty: 3, unit: "шт", group: "Овощи", staple: false },
      { name: "Сахар", qty: 100, unit: "г", group: "Бакалея", staple: true },
      { name: "Мята", qty: 1, unit: "пучок", group: "Овощи", staple: false },
      { name: "Вода газированная", qty: 1, unit: "л", group: "Прочее", staple: false }
    ],
    steps: [
      { text: "Сварите сироп из сахара и стакана воды, остудите." },
      { text: "Смешайте сок лимонов, сироп, мяту и газировку, добавьте лёд." }
    ], notes: ""
  },
  {
    id: "smoothie-berry", title: "Ягодный смузи", forKid: true,
    category: "Напиток", cuisine: "Американская", photo: "",
    time: 5, difficulty: 1, baseServings: 2, tags: ["детское", "быстро", "ягоды"],
    ingredients: [
      { name: "Замороженные ягоды", qty: 200, unit: "г", group: "Заморозка", staple: false },
      { name: "Банан", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Йогурт", qty: 200, unit: "г", group: "Молочное", staple: false },
      { name: "Мёд", qty: 1, unit: "ст.л.", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Пробейте все ингредиенты блендером до однородности." }
    ], notes: ""
  },

  /* ===================== Десерты и выпечка ===================== */
  {
    id: "charlotte-apple", title: "Шарлотка с яблоками", forKid: true,
    category: "Выпечка", cuisine: "Русская", photo: "",
    time: 50, difficulty: 1, baseServings: 6, tags: ["детское", "яблоки", "сладкое"],
    ingredients: [
      { name: "Яблоки", qty: 4, unit: "шт", group: "Овощи", staple: false },
      { name: "Яйцо", qty: 4, unit: "шт", group: "Молочное", staple: false },
      { name: "Мука", qty: 200, unit: "г", group: "Бакалея", staple: true },
      { name: "Сахар", qty: 200, unit: "г", group: "Бакалея", staple: true },
      { name: "Ванилин", qty: 1, unit: "щепотка", group: "Бакалея", staple: false }
    ],
    steps: [
      { text: "Взбейте яйца с сахаром до пышности, всыпьте муку." },
      { text: "Выложите нарезанные яблоки в форму, залейте тестом." },
      { text: "Выпекайте при 180° 35 минут.", timer: 2100 }
    ], notes: ""
  },
  {
    id: "brownie", title: "Брауни", forKid: true,
    category: "Десерт", cuisine: "Американская", photo: "",
    time: 45, difficulty: 1, baseServings: 8, tags: ["детское", "шоколад", "сладкое"],
    ingredients: [
      { name: "Тёмный шоколад", qty: 200, unit: "г", group: "Бакалея", staple: false },
      { name: "Сливочное масло", qty: 150, unit: "г", group: "Молочное", staple: false },
      { name: "Яйцо", qty: 3, unit: "шт", group: "Молочное", staple: false },
      { name: "Сахар", qty: 180, unit: "г", group: "Бакалея", staple: true },
      { name: "Мука", qty: 100, unit: "г", group: "Бакалея", staple: true }
    ],
    steps: [
      { text: "Растопите шоколад с маслом." },
      { text: "Взбейте яйца с сахаром, соедините с шоколадом, вмешайте муку." },
      { text: "Выпекайте при 175° 25 минут до влажной серединки.", timer: 1500 }
    ], notes: ""
  },

  /* ===================== Гарниры ===================== */
  {
    id: "mashed-potatoes", title: "Картофельное пюре", forKid: true,
    category: "Гарнир", cuisine: "Русская", photo: "",
    time: 30, difficulty: 1, baseServings: 4, tags: ["детское", "картофель", "гарнир"],
    ingredients: [
      { name: "Картофель", qty: 800, unit: "г", group: "Овощи", staple: false },
      { name: "Молоко", qty: 150, unit: "мл", group: "Молочное", staple: false },
      { name: "Сливочное масло", qty: 50, unit: "г", group: "Молочное", staple: false },
      { name: "Соль", qty: null, unit: "по вкусу", group: "Специи", staple: true }
    ],
    steps: [
      { text: "Отварите картофель до мягкости, 20 минут.", timer: 1200 },
      { text: "Разомните с горячим молоком и маслом до пышности, посолите." }
    ], notes: ""
  },
  {
    id: "roasted-veggies", title: "Овощи на гриле в духовке", forKid: false,
    category: "Гарнир", cuisine: "Французская", photo: "",
    time: 35, difficulty: 1, baseServings: 4, tags: ["овощи", "веган", "запечённое"],
    ingredients: [
      { name: "Кабачок", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Баклажан", qty: 1, unit: "шт", group: "Овощи", staple: false },
      { name: "Болгарский перец", qty: 2, unit: "шт", group: "Овощи", staple: false },
      { name: "Оливковое масло", qty: 3, unit: "ст.л.", group: "Бакалея", staple: true },
      { name: "Прованские травы", qty: 1, unit: "ст.л.", group: "Специи", staple: false }
    ],
    steps: [
      { text: "Нарежьте овощи крупно, перемешайте с маслом и травами." },
      { text: "Запекайте при 200° 25 минут, перемешав в середине.", timer: 1500 }
    ], notes: ""
  }
];

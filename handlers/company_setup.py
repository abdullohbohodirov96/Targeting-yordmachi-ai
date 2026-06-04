"""
Kompaniya sozlash wizardi — aiogram FSM bilan.
/start da profil yo'q bo'lsa yoki /setup buyrug'ida ishga tushadi.
"""
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardRemove
from utils.company_profile import save_profile, get_company_name
from config.settings import ADMIN_ID
from utils.logger import logger

router = Router()


class CompanySetup(StatesGroup):
    name = State()
    industry = State()
    products = State()
    audience = State()
    goals = State()
    location = State()
    budget = State()


def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


async def begin_setup(message: types.Message, state: FSMContext):
    """Wizardni boshlaydi — istalgan handlerdan chaqirish mumkin."""
    await state.set_state(CompanySetup.name)
    await message.answer(
        "👋 *Assalomu alaykum! Men sizning shaxsiy AI Targeting Mutaxassisigingizman.*\n\n"
        "Siz bilan samarali ishlash uchun avval kompaniyangiz haqida bir oz ma'lumot olmoqchiman.\n"
        "Bu ma'lumotlar menga sizga *aniq va moslashtirilgan* tavsiyalar berishimga yordam beradi.\n\n"
        "📍 *1/7 — Kompaniyangizning nomi nima?*\n"
        "_(Masalan: Dunyabunya, TechMart, UniFood...)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(CompanySetup.name, F.text)
async def setup_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Iltimos, kompaniya nomini to'g'ri kiriting.")
        return
    await state.update_data(name=name)
    await state.set_state(CompanySetup.industry)
    await message.answer(
        "✅ Yaxshi!\n\n"
        "📍 *2/7 — Qaysi sohada ishlayman?*\n"
        "_(Masalan: Qurilish materiallari, Oziq-ovqat, Elektronika, Ko'chmas mulk, Kosmetika, Kiyim...)_",
        parse_mode="Markdown",
    )


@router.message(CompanySetup.industry, F.text)
async def setup_industry(message: types.Message, state: FSMContext):
    await state.update_data(industry=message.text.strip())
    await state.set_state(CompanySetup.products)
    await message.answer(
        "✅ Tushunarli!\n\n"
        "📍 *3/7 — Asosiy mahsulot yoki xizmatlaringiz nimalar?*\n"
        "_(Masalan: Gipsokarton, kafel, santexnika, eshiklar — yoki xizmat turlari)_",
        parse_mode="Markdown",
    )


@router.message(CompanySetup.products, F.text)
async def setup_products(message: types.Message, state: FSMContext):
    await state.update_data(products=message.text.strip())
    await state.set_state(CompanySetup.audience)
    await message.answer(
        "✅ Aniq!\n\n"
        "📍 *4/7 — Maqsadli auditoriyangiz kim?*\n"
        "_(Masalan: Uy qurayotganlar, 25-45 yosh erkaklar, ustalar, tadbirkorlar, ayollar...)_",
        parse_mode="Markdown",
    )


@router.message(CompanySetup.audience, F.text)
async def setup_audience(message: types.Message, state: FSMContext):
    await state.update_data(target_audience=message.text.strip())
    await state.set_state(CompanySetup.goals)
    await message.answer(
        "✅ Zo'r!\n\n"
        "📍 *5/7 — Reklama maqsadingiz nima?*\n"
        "_(Masalan: Lead generation, do'konga tashrif, onlayn sotish, brend tanilishi, app install...)_",
        parse_mode="Markdown",
    )


@router.message(CompanySetup.goals, F.text)
async def setup_goals(message: types.Message, state: FSMContext):
    await state.update_data(goals=message.text.strip())
    await state.set_state(CompanySetup.location)
    await message.answer(
        "✅ Tushunarli!\n\n"
        "📍 *6/7 — Qaysi shahar yoki hududda reklama berasiz?*\n"
        "_(Masalan: Toshkent, butun O'zbekiston, Samarqand, Namangan...)_",
        parse_mode="Markdown",
    )


@router.message(CompanySetup.location, F.text)
async def setup_location(message: types.Message, state: FSMContext):
    await state.update_data(location=message.text.strip())
    await state.set_state(CompanySetup.budget)
    await message.answer(
        "✅ Tushunarli!\n\n"
        "📍 *7/7 — Taxminiy oylik reklama byudjetingiz qancha?*\n"
        "_(Masalan: $200, $500, $1000... Agar aytgingiz kelmasa — 'skip' yozing)_",
        parse_mode="Markdown",
    )


@router.message(CompanySetup.budget, F.text)
async def setup_budget(message: types.Message, state: FSMContext):
    budget_text = message.text.strip()
    if budget_text.lower() in ["skip", "o'tkazib", "-", "bilmayman", "sir"]:
        budget_text = None

    data = await state.get_data()
    data["monthly_budget"] = budget_text
    data["is_setup"] = True

    save_profile(data)
    await state.clear()

    company_name = data.get("name", "Kompaniyangiz")
    await message.answer(
        f"✅ *Ajoyib! Kompaniya profili saqlandi!*\n\n"
        f"🏢 Nomi: {data.get('name', '—')}\n"
        f"🏭 Soha: {data.get('industry', '—')}\n"
        f"📦 Mahsulotlar: {data.get('products', '—')}\n"
        f"🎯 Auditoriya: {data.get('target_audience', '—')}\n"
        f"🚀 Maqsad: {data.get('goals', '—')}\n"
        f"📍 Joylashuv: {data.get('location', '—')}\n"
        f"💰 Byudjet: {data.get('monthly_budget') or '—'}\n\n"
        f"Endi men *{company_name}* uchun maxsus moslashtirilgan "
        f"AI targeting mutaxassisi sifatida xizmat qilaman!\n\n"
        f"👉 /help — barcha imkoniyatlar\n"
        f"👉 /setup — profilni qayta sozlash",
        parse_mode="Markdown",
    )
    logger.info(f"Kompaniya profili saqlandi: {company_name}")


@router.message(Command("setup"))
async def cmd_setup(message: types.Message, state: FSMContext):
    """Profilni qayta sozlash buyrug'i."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Bu buyruq faqat admin uchun.")
        return
    await begin_setup(message, state)

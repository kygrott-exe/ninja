import asyncio, gzip, json, copy, io, os, random, string, logging
from pathlib import Path

import lottie
from lottie.utils.font import RawFontRenderer
from lottie import objects, NVector, Color
from lottie.objects.shapes import Fill

from aiogram import Bot, Dispatcher, F
from aiogram.types import (Message, CallbackQuery,
                            InlineKeyboardMarkup, InlineKeyboardButton,
                            BufferedInputFile)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR     = Path(__file__).parent.resolve()
LOTTIES_DIR  = BASE_DIR / "lotties"
DEFAULT_FONT = str(BASE_DIR / "Anton-Regular.ttf")

BOT_TOKEN    = os.getenv("BOT_TOKEN", "8694299888:AAGLt4aTK8jbRisFAgklNZ58VECGY_GliWQ")
LOGO_ID      = "mylogo"
COLOR_BA     = "BA0047"
COLOR_FF     = "FF4A52"
COLOR_NEW    = "44BEF9"
COLOR_WHITE  = "FFFFFF"
ALLOWED_USER = 1899208318 #YourID

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())


class S(StatesGroup):
    select     = State()
    type       = State()
    ask_ba     = State()
    ask_ff     = State()
    json_file  = State()
    text_input = State()
    svg_file   = State()
    logo_c1    = State()
    logo_c2    = State()
    scale      = State()


# ── Lottie utils ──────────────────────────────────────────────────────────────
def hex_to_rgba(h: str) -> list:
    h = h.lstrip("#")
    if len(h) == 3: h = "".join(c*2 for c in h)
    if len(h) != 6: raise ValueError
    return [int(h[i:i+2], 16)/255 for i in (0, 2, 4)] + [1.0]


def rgba_close(a: list, b: list, tol: float = 0.06) -> bool:
    return all(abs(a[i] - b[i]) < tol for i in range(3))


def color_exists(obj, target: list) -> bool:
    """fl, st, gf, gs — searches for all color types"""
    if isinstance(obj, dict):
        ty = obj.get("ty")

        # Simple fill / stroke
        if ty in ("fl", "st"):
            k = obj.get("c", {}).get("k")
            if isinstance(k, list):
                if len(k) == 4 and isinstance(k[0], (int, float)):
                    if rgba_close(k, target): return True
                else:
                    for kf in k:
                        if isinstance(kf, dict):
                            for fld in ("s", "e"):
                                v = kf.get(fld)
                                if isinstance(v, list) and len(v) >= 3:
                                    if rgba_close(v, target): return True

        # Gradient fill / stroke — format: [pos,r,g,b, pos,r,g,b, ...]
        if ty in ("gf", "gs"):
            gk = obj.get("g", {}).get("k", {})
            kvals = gk.get("k") if isinstance(gk, dict) else gk
            if isinstance(kvals, list) and len(kvals) >= 4:
                step = 4  # p count (p) * 4
                for i in range(0, len(kvals) - 3, step):
                    rgb = [kvals[i+1], kvals[i+2], kvals[i+3]]
                    if rgba_close(rgb + [1.0], target): return True

        for v in obj.values():
            if color_exists(v, target): return True
    elif isinstance(obj, list):
        for item in obj:
            if color_exists(item, target): return True
    return False


def replace_color_smart(obj, target: list, new: list, only_stroke: bool = False):
    """
    fl, st → simple color replacement.
    gf, gs → replace each stop color inside the gradient.
    If only_stroke=True, only touches st type.
    """
    if isinstance(obj, dict):
        ty = obj.get("ty")

        # ── Simple fill / stroke ──────────────────────────────────────────────
        if ty in ("fl", "st"):
            if not (only_stroke and ty != "st"):
                k = obj.get("c", {}).get("k")
                if isinstance(k, list):
                    if len(k) == 4 and isinstance(k[0], (int, float)):
                        if rgba_close(k, target):
                            obj["c"]["k"] = new
                    else:
                        for kf in k:
                            if isinstance(kf, dict):
                                for fld in ("s", "e"):
                                    v = kf.get(fld)
                                    if isinstance(v, list) and len(v) >= 3:
                                        if rgba_close(v, target):
                                            kf[fld] = new

        # ── Gradient fill / stroke ───────────────────────────────────────────
        elif ty in ("gf", "gs"):
            if not only_stroke:   # if gradient-stroke, only_stroke should not affect it
                gk = obj.get("g", {}).get("k", {})
                kvals = gk.get("k") if isinstance(gk, dict) else None
                if isinstance(kvals, list) and len(kvals) >= 4:
                    step = 4
                    p = obj.get("g", {}).get("p", len(kvals) // step)
                    for i in range(0, p * step, step):
                        if i + 3 < len(kvals):
                            rgb = [kvals[i+1], kvals[i+2], kvals[i+3]]
                            if rgba_close(rgb + [1.0], target):
                                kvals[i+1] = new[0]
                                kvals[i+2] = new[1]
                                kvals[i+3] = new[2]

        # Recursion
        for v in obj.values():
            replace_color_smart(v, target, new, only_stroke)
    elif isinstance(obj, list):
        for item in obj:
            replace_color_smart(item, target, new, only_stroke)


def recolor_logo(obj, new: list):
    """Replaces ALL colors (fl, st, gf, gs) inside the logo with a new color"""
    if isinstance(obj, dict):
        ty = obj.get("ty")

        if ty in ("fl", "st"):
            k = obj.get("c", {}).get("k")
            if isinstance(k, list):
                if len(k) == 4 and isinstance(k[0], (int, float)):
                    obj["c"]["k"] = new
                else:
                    for kf in k:
                        if isinstance(kf, dict):
                            for fld in ("s", "e"):
                                if isinstance(kf.get(fld), list) and len(kf[fld]) >= 3:
                                    kf[fld] = new

        elif ty in ("gf", "gs"):
            gk = obj.get("g", {}).get("k", {})
            kvals = gk.get("k") if isinstance(gk, dict) else None
            if isinstance(kvals, list) and len(kvals) >= 4:
                p = obj.get("g", {}).get("p", len(kvals) // 4)
                for i in range(0, p * 4, 4):
                    if i + 3 < len(kvals):
                        kvals[i+1] = new[0]
                        kvals[i+2] = new[1]
                        kvals[i+3] = new[2]

        for v in obj.values(): recolor_logo(v, new)
    elif isinstance(obj, list):
        for i in obj: recolor_logo(i, new)


def make_text_layers(text: str, color: list) -> list:
    r, g, b, a = color
    n = len(text)
    fs = 200 if n<=3 else 170 if n<=4 else 140 if n<=6 else 110 if n<=8 else 85
    renderer = RawFontRenderer(DEFAULT_FONT)
    group_measure = renderer.render(text, fs, NVector(0, 0))
    bbox = group_measure.bounding_box()
    if bbox is not None:
        bx = bbox.x1 if hasattr(bbox, 'x1') else bbox[0]
        by = bbox.y1 if hasattr(bbox, 'y1') else bbox[1]
        bw = (bbox.x2 if hasattr(bbox, 'x2') else bbox[2]) - bx
        bh = (bbox.y2 if hasattr(bbox, 'y2') else bbox[3]) - by
        x_pos = 256 - bx - bw / 2
        y_pos = 256 - by - bh / 2
    else:
        x_pos = max(8, (512 - n * fs * 0.58) / 2)
        y_pos = 256 + fs * 0.35
    anim = objects.Animation()
    anim.width = 512; anim.height = 512
    anim.frame_rate = 60; anim.in_point = 0; anim.out_point = 180
    layer = objects.ShapeLayer(); anim.add_layer(layer)
    group = renderer.render(text, fs, NVector(x_pos, y_pos))
    fill = Fill(); fill.color.value = Color(r, g, b, a)
    group.add_shape(fill); layer.add_shape(group)
    src = anim.to_dict()
    layers = src.get("layers", [])
    for lyr in layers:
        ks = lyr.setdefault("ks", {})
        ks["a"] = {"a": 0, "k": [256, 256, 0]}
        ks["p"] = {"a": 0, "k": [256, 256, 0]}
        lyr["ip"] = 0; lyr["op"] = 180; lyr["st"] = 0
    return layers


def make_svg_layers(svg_bytes: bytes) -> list:
    from lottie.parsers.svg import parse_svg_file
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
        tmp.write(svg_bytes); tmp_path = tmp.name
    try: anim = parse_svg_file(tmp_path)
    finally: os.unlink(tmp_path)
    src = anim.to_dict()
    src_layers = src.get("layers", [])
    svg_w, svg_h = src.get("w") or 512, src.get("h") or 512
    cx, cy = 256, 256
    scale_pct = min(512 / svg_w, 512 / svg_h) * 100
    new_layers = []
    for lyr in src_layers:
        l = copy.deepcopy(lyr)
        ks = l.setdefault("ks", {})
        ks["a"] = {"a": 0, "k": [svg_w/2, svg_h/2, 0]}
        ks["p"] = {"a": 0, "k": [cx, cy, 0]}
        ks["s"] = {"a": 0, "k": [scale_pct, scale_pct, 100]}
        l["ip"] = 0; l["op"] = 180; l["st"] = 0
        new_layers.append(l)
    return new_layers


# ── Logo inject ───────────────────────────────────────────────────────────────
def build_anim(anim_data: dict, logo_layers: list, extra_assets: list,
               scale: float,
               ba_color: list | None, ff_color: list | None,
               logo_c1: list | None, logo_c2: list | None,
               file_num: int = 1) -> dict:
    out = copy.deepcopy(anim_data)

    t_ba    = hex_to_rgba(COLOR_BA)
    t_ff    = hex_to_rgba(COLOR_FF)
    t_new   = hex_to_rgba(COLOR_NEW)
    t_white = hex_to_rgba(COLOR_WHITE)

    # color_exists now also checks gf/gs
    has_special = (color_exists(out, t_ba)
                   or color_exists(out, t_ff)
                   or (file_num >= 67 and color_exists(out, t_new)))
    logo_color = logo_c1 if has_special else logo_c2

    # find mylogo asset
    logo_asset = next((a for a in out.get("assets", [])
                       if "LOGO" in (a.get("nm") or "").upper()
                       or (a.get("id") or "").upper() == LOGO_ID.upper()), None)
    if not logo_asset:
        out.setdefault("assets", []).append({"id": LOGO_ID, "layers": []})
        logo_asset = out["assets"][-1]
    logo_id = logo_asset.get("id")

    # save ip/op/st of refId layers
    def collect_ref_timing(layers):
        result = []
        for lyr in layers:
            if lyr.get("refId") == logo_id:
                result.append({"ip": lyr.get("ip"), "op": lyr.get("op"),
                                "st": lyr.get("st"), "_ref": lyr})
            if "layers" in lyr:
                result.extend(collect_ref_timing(lyr["layers"]))
        return result

    all_logo_refs = collect_ref_timing(out.get("layers", []))
    for asset in out.get("assets", []):
        if "layers" in asset:
            all_logo_refs.extend(collect_ref_timing(asset["layers"]))

    # Prepare logo layers
    prepared = copy.deepcopy(logo_layers)
    if logo_color:
        recolor_logo(prepared, logo_color)   # also repaints gf/gs
    for i, lyr in enumerate(prepared):
        ks = lyr.setdefault("ks", {})
        ks["s"] = {"a": 0, "k": [scale, scale, 100]}
        lyr["ip"] = 0; lyr["op"] = 9999; lyr["st"] = 0
        lyr["ind"] = i + 1
        lyr["nm"] = f"Injected Logo {i+1}"

    logo_asset["ip"] = 0
    logo_asset["op"] = 9999
    logo_asset["layers"] = prepared

    # Restore original timing
    for ref in all_logo_refs:
        lyr = ref["_ref"]
        if ref["ip"] is not None: lyr["ip"] = ref["ip"]
        if ref["op"] is not None: lyr["op"] = ref["op"]
        if ref["st"] is not None: lyr["st"] = ref["st"]

    # Extra assets
    if extra_assets:
        ex_ids = {a.get("id") for a in out["assets"]}
        for a in extra_assets:
            if a.get("id") not in ex_ids:
                out["assets"].append(copy.deepcopy(a))

    # ── COLOR REPLACEMENT (fl, st, gf, gs) ──────────────────────────────────
    if ba_color:
        replace_color_smart(out, t_ba, ba_color)
        replace_color_smart(out, t_white, ba_color, only_stroke=True)
    if ff_color:
        replace_color_smart(out, t_ff, ff_color)
        replace_color_smart(out, t_new, ff_color)

    return out


def protect_json(d: dict) -> dict:
    fake_layer = {
        "ddd": 0, "ind": 999, "ty": 4, "nm": ".", "sr": 1,
        "ks": {
            "o": {"a": 0, "k": 0}, "r": {"a": 0, "k": 0},
            "p": {"a": 0, "k": [0,0,0]}, "a": {"a": 0, "k": [0,0,0]},
            "s": {"a": 0, "k": [0,0,0]}
        },
        "ao": 0, "sh\u0430\u0440es": [{"ty": "gr", "it": [], "nm": "."}],
        "ip": d.get("ip", 0), "op": d.get("op", 180), "st": 0, "bm": 0
    }
    if d.get("assets"):
        for a in d["assets"]:
            if isinstance(a.get("layers"), list):
                a["layers"].insert(0, copy.deepcopy(fake_layer))
    if isinstance(d.get("layers"), list):
        d["layers"].insert(0, copy.deepcopy(fake_layer))
    return d


def to_tgs(d: dict) -> bytes:
    buf = io.BytesIO()
    data = copy.deepcopy(d); data["tgs"] = 1
    protect_json(data)
    with gzip.open(buf, "wb") as gz:
        gz.write(json.dumps(data, separators=(",", ":")).encode())
    return buf.getvalue()


def get_001() -> dict | None:
    files = sorted(LOTTIES_DIR.glob("*.json"))
    if not files: return None
    with open(files[0], encoding="utf-8") as f: return json.load(f)


def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🖼 JSON (Logo)", callback_data="json"),
        InlineKeyboardButton(text="✏️ Text",        callback_data="text"),
        InlineKeyboardButton(text="🎨 SVG",         callback_data="svg"),
    ]])


def select_kb():
    total = len(sorted(LOTTIES_DIR.glob("*.json")))
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"🎯 FULL ({total} items)", callback_data="full"),
    ]])


def parse_indices(text: str) -> list[int] | None:
    parts = text.replace(",", ".").replace(" ", ".").split(".")
    result = []
    for p in parts:
        p = p.strip()
        if not p: continue
        try:
            n = int(p)
            if n < 1 or n > 999: return None
            result.append(n)
        except ValueError: return None
    return result


@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    if msg.from_user.id != ALLOWED_USER: return
    await state.clear()
    await msg.answer("Assalomu alaykum! Choose animation type:", reply_markup=main_kb())


@dp.callback_query(F.data.in_(["json", "text", "svg"]))
async def cb_type(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ALLOWED_USER: return
    await call.answer(); await state.update_data(mode=call.data)
    await call.message.edit_text("Which animations should we change?", reply_markup=select_kb())
    await state.set_state(S.select)


@dp.callback_query(S.select, F.data == "full")
async def cb_select_full(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ALLOWED_USER: return
    await call.answer(); await state.update_data(selected=list(range(1, 140)))
    await call.message.edit_text(
        "🎨 Enter color for <b>BA0047</b> (and white Stroke):\n<i>skip → no change</i>",
        parse_mode="HTML")
    await state.set_state(S.ask_ba)


@dp.message(S.select)
async def select_indices(msg: Message, state: FSMContext):
    if msg.from_user.id != ALLOWED_USER: return
    indices = parse_indices(msg.text)
    if indices is None:
        await msg.answer("⚠️ Invalid number format."); return
    await state.update_data(selected=indices)
    await msg.answer(
        "🎨 Enter color for <b>BA0047</b> (and white Stroke):\n<i>skip → no change</i>",
        parse_mode="HTML")
    await state.set_state(S.ask_ba)


@dp.message(S.ask_ba)
async def ask_ba(msg: Message, state: FSMContext):
    if msg.from_user.id != ALLOWED_USER: return
    t = msg.text.strip(); color = None
    if t.lower() != "skip":
        try: color = hex_to_rgba(t)
        except:
            await msg.answer("⚠️ Invalid HEX color."); return
    await state.update_data(ba_color=color)
    await msg.answer(
        "🎨 New color for <b>FF4A52 & 44BEF9</b> (HEX):\n<i>skip → no change</i>",
        parse_mode="HTML")
    await state.set_state(S.ask_ff)


@dp.message(S.ask_ff)
async def ask_ff(msg: Message, state: FSMContext):
    if msg.from_user.id != ALLOWED_USER: return
    t = msg.text.strip(); color = None
    if t.lower() != "skip":
        try: color = hex_to_rgba(t)
        except:
            await msg.answer("⚠️ Invalid HEX color."); return
    await state.update_data(ff_color=color)
    d = await state.get_data()
    if d["mode"] == "json":
        await msg.answer("📁 Send Logo <b>.json</b> file:", parse_mode="HTML")
        await state.set_state(S.json_file)
    elif d["mode"] == "svg":
        await msg.answer("🎨 Send Logo <b>.svg</b> file:", parse_mode="HTML")
        await state.set_state(S.svg_file)
    else:
        await msg.answer("✏️ Enter Emoji text:", parse_mode="HTML")
        await state.set_state(S.text_input)


@dp.message(S.json_file, F.document)
async def got_json(msg: Message, state: FSMContext):
    if msg.from_user.id != ALLOWED_USER: return
    if not (msg.document.file_name or "").endswith(".json"):
        await msg.answer("⚠️ Only .json file!"); return
    f = await bot.get_file(msg.document.file_id)
    buf = io.BytesIO()
    await bot.download_file(f.file_path, buf); buf.seek(0)
    data = json.load(buf)
    await state.update_data(layers=data.get("layers", []),
                             extra=[a for a in data.get("assets", []) if a.get("id") != LOGO_ID])
    await msg.answer("🎨 <b>Logo color 1</b> (for those with BA/FF):", parse_mode="HTML")
    await state.set_state(S.logo_c1)


@dp.message(S.svg_file, F.document)
async def got_svg(msg: Message, state: FSMContext):
    if msg.from_user.id != ALLOWED_USER: return
    if not (msg.document.file_name or "").lower().endswith(".svg"):
        await msg.answer("⚠️ Only .svg file!"); return
    f = await bot.get_file(msg.document.file_id)
    buf = io.BytesIO()
    await bot.download_file(f.file_path, buf); buf.seek(0)
    layers = await asyncio.get_running_loop().run_in_executor(None, lambda: make_svg_layers(buf.read()))
    await state.update_data(layers=layers, extra=[])
    await msg.answer("🎨 <b>Logo color 1</b> (for those with BA/FF):", parse_mode="HTML")
    await state.set_state(S.logo_c1)


@dp.message(S.text_input)
async def got_text(msg: Message, state: FSMContext):
    if msg.from_user.id != ALLOWED_USER: return
    await state.update_data(user_text=msg.text.strip(), layers=None, extra=[])
    await msg.answer("🎨 <b>Logo color 1</b> (for those with BA/FF):", parse_mode="HTML")
    await state.set_state(S.logo_c1)


@dp.message(S.logo_c1)
async def got_logo_c1(msg: Message, state: FSMContext):
    if msg.from_user.id != ALLOWED_USER: return
    t = msg.text.strip(); color = None
    if t.lower() != "skip":
        try: color = hex_to_rgba(t)
        except:
            await msg.answer("⚠️ Invalid HEX."); return
    await state.update_data(logo_c1=color)
    await msg.answer("🎨 <b>Logo color 2</b> (for those without BA/FF):", parse_mode="HTML")
    await state.set_state(S.logo_c2)


@dp.message(S.logo_c2)
async def got_logo_c2(msg: Message, state: FSMContext):
    if msg.from_user.id != ALLOWED_USER: return
    t = msg.text.strip(); color = None
    if t.lower() != "skip":
        try: color = hex_to_rgba(t)
        except:
            await msg.answer("⚠️ Invalid HEX."); return
    await state.update_data(logo_c2=color)
    d = await state.get_data()
    if d.get("layers") is None:
        c = d.get("logo_c1") or color or hex_to_rgba("FFFFFF")
        d["layers"] = await asyncio.get_running_loop().run_in_executor(
            None, lambda: make_text_layers(d["user_text"], c))
        await state.update_data(layers=d["layers"])
    await state.update_data(scale=100.0)
    await send_preview(msg, state)
    await state.set_state(S.scale)


async def send_preview(msg: Message, state: FSMContext):
    d = await state.get_data()
    anim = get_001()
    if not anim:
        await msg.answer(f"❌ {LOTTIES_DIR}/ is empty!"); return
    mod = build_anim(anim, d["layers"], d.get("extra", []), d.get("scale", 100.0),
                     d.get("ba_color"), d.get("ff_color"),
                     d.get("logo_c1"), d.get("logo_c2"), 1)
    await msg.answer_document(BufferedInputFile(to_tgs(mod), filename="preview.tgs"),
                              caption=f"Preview - {d['scale']}%")


@dp.message(S.scale)
async def scale_input(msg: Message, state: FSMContext):
    if msg.from_user.id != ALLOWED_USER: return
    t = msg.text.strip()
    if t.upper() == "DONE":
        await run_pack(msg, await state.get_data()); await state.clear(); return
    d = await state.get_data(); cur = d.get("scale", 100.0)
    try:
        if t.startswith("+"): new_s = cur + float(t[1:])
        elif t.startswith("-"): new_s = cur - float(t[1:])
        else: new_s = float(t)
    except: return
    await state.update_data(scale=new_s)
    await send_preview(msg, state)


async def run_pack(msg: Message, d: dict):
    uid, me = msg.from_user.id, await bot.get_me()
    name = f"pk{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}_by_{me.username}"
    stat = await msg.answer(f"⚙️ Processing... <code>{name}</code>", parse_mode="HTML")
    files = []
    for fp in sorted(LOTTIES_DIR.glob("*.json")):
        try:
            n = int(fp.stem)
            if n in set(d.get("selected", [])): files.append((fp, n))
        except: pass
    created = False; ok = 0
    for i, (fp, n) in enumerate(files):
        try:
            with open(fp, encoding="utf-8") as f: anim = json.load(f)
            mod = build_anim(anim, d["layers"], d.get("extra", []), d.get("scale", 100.0),
                             d.get("ba_color"), d.get("ff_color"),
                             d.get("logo_c1"), d.get("logo_c2"), n)
            sd = {"sticker": BufferedInputFile(to_tgs(mod), filename="s.tgs"),
                  "emoji_list": ["⭐️"], "format": "animated"}
            if not created:
                await bot.create_new_sticker_set(user_id=uid, name=name,
                                                  title=f"Pack {name[:5]}",
                                                  stickers=[sd], sticker_type="custom_emoji")
                created = True
            else:
                await bot.add_sticker_to_set(user_id=uid, name=name, sticker=sd)
            ok += 1
            if ok % 10 == 0:
                await stat.edit_text(f"⚙️ {ok}/{len(files)} ✅")
        except Exception as e:
            logger.error(f"#{n} error: {e}")
    if created:
        await stat.edit_text(
            f"✅ Ready!\n🔗 <a href='https://t.me/addemoji/{name}'>t.me/addemoji/{name}</a>",
            parse_mode="HTML")
    else:
        await stat.edit_text("❌ Error.")


async def main():
    logger.info(f"BASE_DIR   : {BASE_DIR}")
    logger.info(f"LOTTIES_DIR: {LOTTIES_DIR}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

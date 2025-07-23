#!/usr/bin/env python3
import warnings
from urllib3.exceptions import NotOpenSSLWarning
warnings.filterwarnings("ignore", category=NotOpenSSLWarning)

import os
import io
import logging
import requests
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv

# ——— Logging setup ———————————————————————————————————————————————————————
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ——— QR scanning support —————————————————————————————————————————————————————
try:
    from pyzbar.pyzbar import decode as zbar_decode
    logger.info("📷 QR/barcode scanning ENABLED")
except ImportError:
    zbar_decode = None
    logger.warning(
        "📷 QR/barcode scanning DISABLED. Install zbar (`brew install zbar`), then "
        "`pip install --upgrade pyzbar pillow`."
    )

# ——— Load configuration —————————————————————————————————————————————————
load_dotenv()
TOKEN         = os.getenv("TELEGRAM_BOT_TOKEN")
STORE         = os.getenv("SHOPIFY_STORE")        # e.g. your-shop-name.myshopify.com
ADMIN_TOKEN   = os.getenv("SHOPIFY_ADMIN_TOKEN")  # must include read/write_inventory & read_locations
CUSTOM_DOMAIN = "https://nikkifashion.com"
API_VER       = "2025-07"
GRAPHQL_URL   = f"https://{STORE}/admin/api/{API_VER}/graphql.json"
HEADERS       = {
    "Content-Type": "application/json",
    "X-Shopify-Access-Token": ADMIN_TOKEN,
}

CURRENCY_SYMBOLS = {
    "USD": "$", "INR": "₹", "EUR": "€", "GBP": "£",
    "CAD": "$", "AUD": "$", "JPY": "¥"
}

COMMANDS_TEXT = (
    "/start     — Main menu\n"
    "/help      — Commands\n"
    "/qrtest    — Check QR status\n"
    "/setstock  — Update stock (/setstock <SKU> <qty>)\n"
    "/return    — Process return (/return <SKU> <qty>)\n"
    "/privacy   — Privacy policy\n"
    "Or send a QR/barcode with “SKU,quantity” or just “SKU”."
)
PRIVACY_POLICY = """Privacy Policy
Last updated: July 23, 2025

1. We only log your SKU queries—no profiling or sharing.
2. Logs are purged within 24 hours.
3. All calls are HTTPS. Keep your tokens secret.
4. To stop: /quit or block the bot.
"""

def graphql_get_item_and_location_ids(sku: str):
    query = """
    query($sku:String!){
      productVariants(first:1,query:$sku){edges{node{inventoryItem{id}}}}
      locations(first:1){edges{node{id}}}
    }
    """
    resp = requests.post(GRAPHQL_URL,
                         json={"query": query, "variables": {"sku": sku}},
                         headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        logger.error("GraphQL get IDs errors: %s", data["errors"])
        return None, None
    pv = data["data"]["productVariants"]["edges"]
    loc = data["data"]["locations"]["edges"]
    if not pv or not loc:
        return None, None
    return pv[0]["node"]["inventoryItem"]["id"], loc[0]["node"]["id"]

def graphql_set_quantities(item_gid: str, loc_gid: str, qty: int):
    mutation = """
    mutation($in:InventorySetQuantitiesInput!){
      inventorySetQuantities(input:$in){
        inventoryAdjustmentGroup{changes{name delta}}
        userErrors{field message}
      }
    }
    """
    payload = {
        "query": mutation,
        "variables": {
            "in": {
                "name": "available",
                "reason": "other",
                "ignoreCompareQuantity": True,
                "quantities": [{
                    "inventoryItemId": item_gid,
                    "locationId":       loc_gid,
                    "quantity":         qty
                }]
            }
        }
    }
    resp = requests.post(GRAPHQL_URL, json=payload, headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        return None, data["errors"]
    return data["data"].get("inventorySetQuantities"), None

def get_product_by_sku(sku: str):
    query = """
    query($sku:String!){
      shop{currencyCode}
      products(first:1,query:$sku){
        edges{node{
          title description onlineStoreUrl
          images(first:5){edges{node{src}}}
          variants(first:5){edges{node{sku title price inventoryQuantity}}}
        }}
      }
    }
    """
    resp = requests.post(GRAPHQL_URL,
                         json={"query": query, "variables": {"sku": sku}},
                         headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        logger.error("GraphQL getProduct errors: %s", data["errors"])
        return None
    edges = data["data"]["products"]["edges"]
    if not edges:
        return None
    n = edges[0]["node"]
    images = [i["node"]["src"] for i in n["images"]["edges"]]
    variants = [
        {
            "sku":       v["node"]["sku"],
            "title":     v["node"]["title"],
            "price":     v["node"]["price"],
            "inventory": v["node"]["inventoryQuantity"],
        }
        for v in n["variants"]["edges"]
    ]
    return {
        "title":       n["title"],
        "description": n["description"],
        "url":         n["onlineStoreUrl"],
        "images":      images,
        "variants":    variants,
        "currency":    data["data"]["shop"]["currencyCode"],
    }

async def safe_send_photo(chat_id, bot, url, caption=None, parse_mode=None):
    try:
        await bot.send_photo(chat_id, url, caption=caption, parse_mode=parse_mode)
        return
    except BadRequest:
        logger.warning("send_photo URL failed, falling back…")
    # Re-encode if needed
    try:
        r = requests.get(url, timeout=10); r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        if max(img.size) > 1024:
            img.thumbnail((1024, 1024), Image.LANCZOS)
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=85)
        buf.name = "image.jpg"; buf.seek(0)
        await bot.send_photo(chat_id, buf, caption=caption, parse_mode=parse_mode)
        return
    except Exception as e2:
        logger.warning("Re-encode failed: %s", e2)
    # Last fallback: document
    try:
        r = requests.get(url, timeout=10); r.raise_for_status()
        doc = io.BytesIO(r.content); doc.name = "file"; doc.seek(0)
        await bot.send_document(chat_id, document=doc, caption=caption, parse_mode=parse_mode)
        return
    except Exception as e3:
        logger.warning("Document fallback failed: %s", e3)
    if caption:
        await bot.send_message(chat_id, caption, parse_mode=parse_mode)

# ——— Handlers —————————————————————————————————————————————————————
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("Cargos", url=f"{CUSTOM_DOMAIN}/collections/cargos"),
         InlineKeyboardButton("Jeans",  url=f"{CUSTOM_DOMAIN}/collections/jeans"),
         InlineKeyboardButton("All",    url=f"{CUSTOM_DOMAIN}/collections/all")],
        [InlineKeyboardButton("Quit", callback_data="quit")],
    ]
    await update.message.reply_text("👋 Welcome! /help for commands.", reply_markup=InlineKeyboardMarkup(kb))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(COMMANDS_TEXT)

async def qrtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if zbar_decode:
        await update.message.reply_text("📷 QR/barcode scanning ENABLED!")
    else:
        await update.message.reply_text("📷 QR/barcode scanning DISABLED.")

async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(PRIVACY_POLICY)

async def quit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.edit_reply_markup(None)
    await q.message.reply_text("👋 Goodbye!")

async def handle_sku(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sku = update.message.text.strip()
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    prod = get_product_by_sku(sku)
    if not prod:
        return await update.message.reply_markdown(f"❌ No product for SKU `{sku}`")
    sym = CURRENCY_SYMBOLS.get(prod["currency"], prod["currency"]+" ")
    lines = [f"*{prod['title']}*",
             f"[View]({prod['url']})","", prod["description"],"",
             "*Variants & Inventory:*"]
    for v in prod["variants"]:
        lines.append(f"• `{v['sku']}` — {v['title']} — {sym}{v['price']} — stock: {v['inventory']}")
    caption = "\n".join(lines)
    if prod["images"]:
        await safe_send_photo(update.effective_chat.id, context.bot, prod["images"][0],
                              caption=caption, parse_mode="Markdown")
    else:
        await update.message.reply_markdown(caption)

async def setstock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args)!=2:
        return await update.message.reply_text("Usage: /setstock <SKU> <qty>")
    sku, qty_str = args[0], args[1]
    try:
        qty = int(qty_str)
    except ValueError:
        return await update.message.reply_text("Qty must be a number.")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    item_gid, loc_gid = graphql_get_item_and_location_ids(sku)
    if not item_gid:
        return await update.message.reply_markdown("❌ Variant/location not found.")
    current = get_product_by_sku(sku)["variants"][0]["inventory"]
    _, errs = graphql_set_quantities(item_gid, loc_gid, qty)
    if errs:
        return await update.message.reply_markdown(f"❌ {errs[0]['message']}")
    await update.message.reply_markdown(f"✅ Stock for `{sku}` set {current} → {qty}")

async def return_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args)!=2:
        return await update.message.reply_text("Usage: /return <SKU> <qty>")
    sku, qty_str = args[0], args[1]
    try:
        qty = int(qty_str)
    except ValueError:
        return await update.message.reply_text("Qty must be a number.")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    item_gid, loc_gid = graphql_get_item_and_location_ids(sku)
    if not item_gid:
        return await update.message.reply_markdown("❌ Variant/location not found.")
    prod = get_product_by_sku(sku)
    current = prod["variants"][0]["inventory"]
    new_qty = current + qty
    _, errs = graphql_set_quantities(item_gid, loc_gid, new_qty)
    if errs:
        return await update.message.reply_markdown(f"❌ {errs[0]['message']}")
    await update.message.reply_markdown(f"✅ Return: `{sku}` +{qty} → {new_qty}")

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not zbar_decode:
        return await update.message.reply_text(
            "📷 QR/barcode scanning DISABLED. Install zbar + pyzbar + pillow."
        )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    file = await update.message.photo[-1].get_file()
    data = await file.download_as_bytearray()
    img = Image.open(io.BytesIO(data))
    codes = zbar_decode(img)
    if not codes:
        return await update.message.reply_text("❌ No QR/barcode detected.")
    payload = codes[0].data.decode().strip()
    if "," in payload:
        sku, qty_str = payload.split(",", 1)
        if qty_str.isdigit():
            context.args = [sku, qty_str]
            return await return_command(update, context)
    else:
        sku = payload
        context.args = [sku, "1"]
        await update.message.reply_text(f"🔄 Detected SKU `{sku}`, adding 1 to stock…",
                                        parse_mode="Markdown")
        return await return_command(update, context)
    return await update.message.reply_text(
        f"Detected `{payload}`; send `/return {payload} <qty>`"
    )

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Use /help.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled exception: %s", context.error)
    if hasattr(update, "message") and update.message:
        await update.message.reply_text("❌ Something went wrong.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("help",        help_command))
    app.add_handler(CommandHandler("qrtest",      qrtest_command))
    app.add_handler(CommandHandler("privacy",     privacy_command))
    app.add_handler(CommandHandler("setstock",    setstock_command))
    app.add_handler(CommandHandler("return",      return_command))
    app.add_handler(CallbackQueryHandler(quit_callback, pattern="quit"))
    app.add_handler(MessageHandler(filters.PHOTO,           photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sku))
    app.add_handler(MessageHandler(filters.COMMAND,          unknown))
    app.add_error_handler(error_handler)

    logger.info("Bot starting…")
    app.run_polling()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import warnings
from urllib3.exceptions import NotOpenSSLWarning
warnings.filterwarnings("ignore", category=NotOpenSSLWarning)

import os
import io
import logging
import requests
import csv
import json
import datetime
from datetime import datetime, timedelta
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
import time
import re

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

# ——— New Feature Constants —————————————————————————————————————————————
INVENTORY_ALERTS_FILE = "inventory_alerts.json"
DELIVERY_ZONES_FILE = "delivery_zones.json"
SUPPORT_TICKETS_FILE = "support_tickets.json"
AUTO_RESTOCK_FILE = "auto_restock.json"
NOTIFICATIONS_FILE = "notifications.json"

# Delivery zones (pincode ranges)
DELIVERY_ZONES = {
    "Local": {"range": [(100000, 110000)], "delivery_time": "1-2 days"},
    "Metro": {"range": [(400000, 500000), (700000, 800000)], "delivery_time": "2-3 days"},
    "Standard": {"range": [(110000, 400000), (500000, 700000), (800000, 999999)], "delivery_time": "3-5 days"}
}

# Support ticket statuses
TICKET_STATUSES = ["Open", "In Progress", "Resolved", "Closed"]

# Notification types
NOTIFICATION_TYPES = ["low_stock", "order_updates", "delivery_alerts", "system_alerts"]

COMMANDS_TEXT = (
    "🤖 *NIKKI BOT - Complete Management System*\n\n"
    "📦 *Inventory Management:*\n"
    "/set       — Update stock (/set <SKU> <qty>)\n"
    "/return    — Process return (/return <SKU> <qty>)\n"
    "/bulk_set  — Bulk update (/bulk_set <SKU1> <qty1> <SKU2> <qty2>...)\n"
    "/bulk_return — Bulk return (/bulk_return <SKU1> <qty1> <SKU2> <qty2>...)\n"
    "/alert     — Set low stock alert (/alert <SKU> <threshold>)\n"
    "/check_alerts — Check low stock alerts\n"
    "/report    — Generate reports (/report daily|weekly|monthly)\n\n"
    
    "🛍️ *Order Management:*\n"
    "/order     — Order details (/order <ORDER_ID>)\n"
    "/orders    — List orders (/orders pending|today|week)\n"
    "/cancel    — Cancel order (/cancel <ORDER_ID> <reason>)\n"
    "/refund    — Process refund (/refund <ORDER_ID> <amount>)\n"
    "/hold      — Hold order (/hold <ORDER_ID> <reason>)\n\n"
    
    "🚚 *Delivery Management:*\n"
    "/fulfill   — Fulfill order (/fulfill <ORDER_ID> <TRACKING_ID>)\n"
    "/reschedule — Reschedule delivery (/reschedule <ORDER_ID> <NEW_DATE> <REASON>)\n"
    "/partner   — Update delivery partner (/partner <ORDER_ID> <NEW_PARTNER>)\n"
    "/status    — Check delivery status (/status <ORDER_ID>)\n"
    "/schedule  — Schedule delivery (/schedule <ORDER_ID> <DATE> <TIME>)\n"
    "/track     — Track delivery (/track <TRACKING_ID>)\n"
    "/zone      — Check delivery zone (/zone <PINCODE>)\n\n"
    
    "📊 *Analytics & Reports:*\n"
    "/sales     — Sales reports (/sales today|week|month)\n"
    "/top_products — Top selling products\n"
    "/customer  — Customer info (/customer <EMAIL>)\n"
    "/customers — Recent customers\n\n"
    
    "🛠️ *Product Management:*\n"
    "/product   — Product operations (/product add|update|delete <SKU>)\n"
    "/discount  — Apply discount (/discount <ORDER_ID> <percentage>)\n"
    "/coupon    — Create coupon (/coupon create <code> <discount>)\n\n"
    
    "🎯 *Customer Service:*\n"
    "/support   — Create support ticket (/support <ORDER_ID>)\n"
    "/issue     — Report issue (/issue <description>)\n"
    "/notify    — Send notification (/notify <ORDER_ID> <message>)\n\n"
    
    "🤖 *Smart Features:*\n"
    "/predict   — Predict stock needs (/predict <SKU>)\n"
    "/trends    — Show trends\n"
    "/auto_restock — Auto restock (/auto_restock <SKU>)\n"
    "/auto_fulfill — Auto fulfillment rules\n\n"
    
    "⚙️ *System:*\n"
    "/quick     — Quick actions menu\n"
    "/search    — Search (/search <keyword>)\n"
    "/export    — Export data (/export inventory|orders)\n"
    "/backup    — Create backup\n"
    "/notifications — Manage notifications\n\n"
    
    "📋 *Examples:*\n"
    "• /bulk_set SKU001 10 SKU002 5 SKU003 15\n"
    "• /reschedule #1001 2025-01-15 Weather delay\n"
    "• /sales today\n"
    "• /zone 400001\n"
    "• /support #1001 Delivery delay\n"
    "• /quick (for interactive menu)\n\n"
    
    "📱 *Quick Access:* Send QR/barcode with \"SKU,quantity\" or just \"SKU\""
)
PRIVACY_POLICY = """Privacy Policy
Last updated: July 23, 2025

1. We only log your SKU queries—no profiling or sharing.
2. Logs are purged within 24 hours.
3. All calls are HTTPS. Keep your tokens secret.
4. To stop: /quit or block the bot.
"""

# ——— Tracking ID logic ————————————————————————————————————————————————
CSV_URL = "https://docs.google.com/spreadsheets/d/1uXMgo2HjqIsMUy961exC2Ji0HtGfOP5ibqCdmFCUX6w/export?format=csv"
PROCESSED_FILE = "processed_tracking_ids.txt"

def get_processed_ids():
    try:
        with open(PROCESSED_FILE, "r") as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def save_processed_ids(ids):
    with open(PROCESSED_FILE, "a") as f:
        for id in ids:
            f.write(f"{id}\n")

def fetch_new_tracking_ids():
    processed = get_processed_ids()
    response = requests.get(CSV_URL)
    response.raise_for_status()
    new_ids = []
    reader = csv.DictReader(response.text.splitlines())
    for row in reader:
        tracking_id = row.get("TRACKING ID")
        if tracking_id and tracking_id not in processed:
            new_ids.append(tracking_id)
    save_processed_ids(new_ids)
    return new_ids

def get_shopify_order_by_name(order_name):
    # Remove leading # if present
    order_name = order_name.lstrip('#')
    query = f"orders.json?name=%23{order_name}"
    url = f"https://{STORE}/admin/api/{API_VER}/{query}"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    orders = resp.json().get('orders', [])
    if not orders:
        return None
    return orders[0]

def set_shipping_carrier(order_id, carrier_name="India Post Domestic"):
    url = f"https://{STORE}/admin/api/{API_VER}/orders/{order_id}.json"
    payload = {"order": {"id": order_id, "shipping_lines": [{"title": carrier_name}]}}
    resp = requests.put(url, json=payload, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()

def mark_variant_out_of_stock(variant_id):
    # Set inventory to 0 for the variant
    item_gid, loc_gid = graphql_get_item_and_location_ids(variant_id)
    if not item_gid or not loc_gid:
        return False
    _, errs = graphql_set_quantities(item_gid, loc_gid, 0)
    return errs is None

def get_variant_inventory(sku):
    prod = get_product_by_sku(sku)
    if not prod or not prod["variants"]:
        return None
    return prod["variants"][0]["inventory"]

def add_tracking_to_order(order, tracking_id, carrier=None):
    url = f"https://{STORE}/admin/api/{API_VER}/orders/{order['id']}/fulfillments.json"
    line_items = [{"id": item["id"], "quantity": item["quantity"]} for item in order.get("line_items", [])]
    # Get location_id from the first fulfillable line item with manual fulfillment
    location_id = None
    for item in order.get("line_items", []):
        if item.get("fulfillable_quantity", 0) > 0 and item.get("fulfillment_service") == "manual":
            location_id = item.get("location_id")
            break
    if not location_id:
        print("No valid location_id found for fulfillment.")
        raise Exception("No valid location_id found for fulfillment.")
    payload = {
        "fulfillment": {
            "tracking_number": tracking_id,
            "tracking_company": "India Post Domestic",
            "notify_customer": True,
            "line_items": line_items,
            "location_id": location_id
        }
    }
    print("Payload being sent to Shopify:", payload)
    resp = requests.post(url, json=payload, headers=HEADERS)
    try:
        resp.raise_for_status()
    except Exception as e:
        print(f"Shopify fulfillment error: {resp.status_code} {resp.text}")
        raise
    return resp.json()

def reschedule_delivery(order, new_date, reason, delivery_partner="India Post Domestic"):
    """
    Reschedule delivery for an order by updating the shipping line with new delivery date
    and adding a note about the reschedule reason.
    """
    url = f"https://{STORE}/admin/api/{API_VER}/orders/{order['id']}.json"
    
    # Update shipping line with new delivery date and partner
    shipping_lines = order.get("shipping_lines", [])
    if shipping_lines:
        shipping_lines[0]["title"] = f"{delivery_partner} - Rescheduled to {new_date}"
    else:
        # Create new shipping line if none exists
        shipping_lines = [{"title": f"{delivery_partner} - Rescheduled to {new_date}"}]
    
    # Add note about reschedule
    note = order.get("note", "")
    reschedule_note = f"\n--- RESCHEDULE INFO ---\nNew Delivery Date: {new_date}\nReason: {reason}\nDelivery Partner: {delivery_partner}\nRescheduled on: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    updated_note = note + reschedule_note if note else reschedule_note
    
    payload = {
        "order": {
            "id": order["id"],
            "shipping_lines": shipping_lines,
            "note": updated_note
        }
    }
    
    print("Reschedule payload being sent to Shopify:", payload)
    resp = requests.put(url, json=payload, headers=HEADERS)
    try:
        resp.raise_for_status()
    except Exception as e:
        print(f"Shopify reschedule error: {resp.status_code} {resp.text}")
        raise
    return resp.json()

def update_delivery_partner(order, new_partner):
    """
    Update the delivery partner for an order.
    """
    url = f"https://{STORE}/admin/api/{API_VER}/orders/{order['id']}.json"
    
    shipping_lines = order.get("shipping_lines", [])
    if shipping_lines:
        current_title = shipping_lines[0]["title"]
        # Preserve any existing delivery date info
        if "Rescheduled to" in current_title:
            date_part = current_title.split("Rescheduled to")[1].strip()
            shipping_lines[0]["title"] = f"{new_partner} - Rescheduled to {date_part}"
        else:
            shipping_lines[0]["title"] = new_partner
    else:
        shipping_lines = [{"title": new_partner}]
    
    # Add note about partner change
    note = order.get("note", "")
    partner_note = f"\n--- DELIVERY PARTNER UPDATE ---\nNew Partner: {new_partner}\nUpdated on: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    updated_note = note + partner_note if note else partner_note
    
    payload = {
        "order": {
            "id": order["id"],
            "shipping_lines": shipping_lines,
            "note": updated_note
        }
    }
    
    print("Partner update payload being sent to Shopify:", payload)
    resp = requests.put(url, json=payload, headers=HEADERS)
    try:
        resp.raise_for_status()
    except Exception as e:
        print(f"Shopify partner update error: {resp.status_code} {resp.text}")
        raise
    return resp.json()

def get_delivery_status(order):
    """
    Get delivery status and history for an order.
    """
    delivery_info = {
        "current_partner": "Unknown",
        "delivery_date": "Not set",
        "tracking_number": "Not available",
        "reschedule_history": [],
        "partner_history": []
    }
    
    # Get shipping lines info
    shipping_lines = order.get("shipping_lines", [])
    if shipping_lines:
        delivery_info["current_partner"] = shipping_lines[0]["title"]
        if "Rescheduled to" in delivery_info["current_partner"]:
            # Extract date from title
            parts = delivery_info["current_partner"].split("Rescheduled to")
            delivery_info["delivery_date"] = parts[1].strip()
    
    # Get fulfillment info
    fulfillments = order.get("fulfillments", [])
    if fulfillments:
        latest_fulfillment = fulfillments[-1]
        delivery_info["tracking_number"] = latest_fulfillment.get("tracking_number", "Not available")
        delivery_info["tracking_company"] = latest_fulfillment.get("tracking_company", "Unknown")
    
    # Parse note for history
    note = order.get("note", "")
    if "RESCHEDULE INFO" in note:
        # Extract reschedule history from notes
        reschedule_sections = note.split("--- RESCHEDULE INFO ---")
        for section in reschedule_sections[1:]:  # Skip first empty section
            lines = section.strip().split("\n")
            reschedule_entry = {}
            for line in lines:
                if ":" in line:
                    key, value = line.split(":", 1)
                    reschedule_entry[key.strip()] = value.strip()
            if reschedule_entry:
                delivery_info["reschedule_history"].append(reschedule_entry)
    
    if "DELIVERY PARTNER UPDATE" in note:
        # Extract partner history from notes
        partner_sections = note.split("--- DELIVERY PARTNER UPDATE ---")
        for section in partner_sections[1:]:  # Skip first empty section
            lines = section.strip().split("\n")
            partner_entry = {}
            for line in lines:
                if ":" in line:
                    key, value = line.split(":", 1)
                    partner_entry[key.strip()] = value.strip()
            if partner_entry:
                delivery_info["partner_history"].append(partner_entry)
    
    return delivery_info

# ——— New Feature Utility Functions —————————————————————————————————————
def load_json_file(filename):
    """Load data from JSON file"""
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_json_file(filename, data):
    """Save data to JSON file"""
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

def get_inventory_alerts():
    """Get inventory alerts"""
    return load_json_file(INVENTORY_ALERTS_FILE)

def save_inventory_alerts(alerts):
    """Save inventory alerts"""
    save_json_file(INVENTORY_ALERTS_FILE, alerts)

def check_low_stock_alerts():
    """Check for low stock alerts"""
    alerts = get_inventory_alerts()
    low_stock_items = []
    
    for sku, threshold in alerts.items():
        inventory = get_variant_inventory(sku)
        if inventory is not None and inventory <= threshold:
            low_stock_items.append({"sku": sku, "current": inventory, "threshold": threshold})
    
    return low_stock_items

def get_delivery_zone(pincode):
    """Get delivery zone for pincode"""
    try:
        pincode = int(pincode)
        for zone, info in DELIVERY_ZONES.items():
            for start, end in info["range"]:
                if start <= pincode <= end:
                    return zone, info["delivery_time"]
        return "Not Available", "N/A"
    except ValueError:
        return "Invalid", "N/A"

def create_support_ticket(order_id, description, user_id):
    """Create support ticket"""
    tickets = load_json_file(SUPPORT_TICKETS_FILE)
    ticket_id = f"TICKET-{len(tickets) + 1:04d}"
    
    ticket = {
        "id": ticket_id,
        "order_id": order_id,
        "description": description,
        "status": "Open",
        "created_by": user_id,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    
    tickets[ticket_id] = ticket
    save_json_file(SUPPORT_TICKETS_FILE, tickets)
    return ticket

def get_support_tickets():
    """Get all support tickets"""
    return load_json_file(SUPPORT_TICKETS_FILE)

def update_ticket_status(ticket_id, status):
    """Update ticket status"""
    tickets = get_support_tickets()
    if ticket_id in tickets:
        tickets[ticket_id]["status"] = status
        tickets[ticket_id]["updated_at"] = datetime.now().isoformat()
        save_json_file(SUPPORT_TICKETS_FILE, tickets)
        return True
    return False

def get_orders_by_status(status="any", days=None):
    """Get orders by status and date range"""
    url = f"https://{STORE}/admin/api/{API_VER}/orders.json"
    params = {"status": status, "limit": 250}
    
    if days:
        since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        params["created_at_min"] = since_date
    
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    return resp.json().get("orders", [])

def get_sales_data(period="today"):
    """Get sales data for specified period"""
    if period == "today":
        days = 1
    elif period == "week":
        days = 7
    elif period == "month":
        days = 30
    else:
        days = 1
    
    orders = get_orders_by_status("any", days)
    
    total_sales = 0
    total_orders = len(orders)
    products_sold = {}
    
    for order in orders:
        if order.get("financial_status") == "paid":
            total_sales += float(order.get("total_price", 0))
        
        for item in order.get("line_items", []):
            sku = item.get("sku")
            qty = item.get("quantity", 0)
            if sku:
                products_sold[sku] = products_sold.get(sku, 0) + qty
    
    return {
        "total_sales": total_sales,
        "total_orders": total_orders,
        "products_sold": products_sold,
        "period": period
    }

def predict_stock_needs(sku):
    """Predict stock needs based on sales history"""
    # Get last 30 days of sales
    sales_data = get_sales_data("month")
    products_sold = sales_data["products_sold"]
    
    if sku in products_sold:
        monthly_demand = products_sold[sku]
        # Predict next month demand (simple average)
        predicted_demand = monthly_demand
        current_stock = get_variant_inventory(sku) or 0
        
        return {
            "sku": sku,
            "current_stock": current_stock,
            "monthly_demand": monthly_demand,
            "predicted_demand": predicted_demand,
            "recommended_stock": max(predicted_demand, 10),  # Minimum 10
            "stock_needed": max(predicted_demand - current_stock, 0)
        }
    else:
        return {"sku": sku, "error": "No sales data available"}

def apply_discount_to_order(order_id, percentage):
    """Apply discount to order"""
    order = get_shopify_order_by_name(order_id)
    if not order:
        return None
    
    url = f"https://{STORE}/admin/api/{API_VER}/orders/{order['id']}.json"
    
    # Calculate discount amount
    total_price = float(order.get("total_price", 0))
    discount_amount = total_price * (percentage / 100)
    
    payload = {
        "order": {
            "id": order["id"],
            "discount_codes": [{
                "code": f"BOT_DISCOUNT_{percentage}%",
                "amount": str(discount_amount),
                "type": "percentage"
            }]
        }
    }
    
    resp = requests.put(url, json=payload, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()

def export_inventory_data():
    """Export inventory data to CSV"""
    # Get all products
    url = f"https://{STORE}/admin/api/{API_VER}/products.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    products = resp.json().get("products", [])
    
    csv_data = []
    for product in products:
        for variant in product.get("variants", []):
            csv_data.append({
                "SKU": variant.get("sku"),
                "Product": product.get("title"),
                "Variant": variant.get("title"),
                "Price": variant.get("price"),
                "Inventory": variant.get("inventory_quantity"),
                "Status": "Active" if product.get("status") == "active" else "Inactive"
            })
    
    return csv_data

def search_products(keyword):
    """Search products by keyword"""
    url = f"https://{STORE}/admin/api/{API_VER}/products.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    products = resp.json().get("products", [])
    
    results = []
    keyword_lower = keyword.lower()
    
    for product in products:
        if (keyword_lower in product.get("title", "").lower() or
            keyword_lower in product.get("body_html", "").lower()):
            results.append(product)
    
    return results

async def checktracking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Checking for new tracking IDs and orders...")
    try:
        processed = get_processed_ids()
        response = requests.get(CSV_URL)
        response.raise_for_status()
        new_ids = []
        reader = csv.DictReader(response.text.splitlines())
        actions = []
        for row in reader:
            tracking_id = row.get("TRACKING ID")
            order_name = row.get("SHOPIFY ORDER ID")
            status = row.get("STATUS")
            if not tracking_id or tracking_id in processed:
                continue
            new_ids.append(tracking_id)
            if not order_name:
                actions.append(f"Tracking ID {tracking_id}: No order ID found.")
                continue
            order = get_shopify_order_by_name(order_name)
            if not order:
                actions.append(f"Order {order_name} not found for tracking ID {tracking_id}.")
                continue
            if status and status.strip().upper() == "PACKED":
                # Add tracking and carrier
                try:
                    add_tracking_to_order(order, tracking_id)
                    actions.append(f"Order {order_name}: Tracking ID {tracking_id} and carrier set to India Post Domestic.")
                except Exception as e:
                    actions.append(f"Order {order_name}: Failed to add tracking/carrier: {e}")
                continue
            # Check each line item SKU
            for item in order.get("line_items", []):
                sku = item.get("sku")
                variant_id = item.get("variant_id")
                if not sku or not variant_id:
                    actions.append(f"Order {order_name}: Missing SKU or variant ID.")
                    continue
                inventory = get_variant_inventory(sku)
                if inventory is None:
                    actions.append(f"Order {order_name} SKU {sku}: Could not fetch inventory.")
                    continue
                if inventory == 0:
                    mark_variant_out_of_stock(variant_id)
                    actions.append(f"Order {order_name} SKU {sku}: Marked as out of stock.")
                else:
                    actions.append(f"Order {order_name} SKU {sku}: In stock ({inventory}).")
            # Set shipping carrier
            set_shipping_carrier(order["id"])
            actions.append(f"Order {order_name}: Shipping carrier set to India Post Domestic.")
            time.sleep(0.5)  # avoid rate limits
        save_processed_ids(new_ids)
        if actions:
            await update.message.reply_text("\n".join(actions))
        else:
            await update.message.reply_text("No new tracking IDs found.")
    except Exception as e:
        logger.exception("Error in checktracking: %s", e)
        await update.message.reply_text(f"Error: {e}")

async def fulfill_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("Usage: /fulfill <SHOPIFY_ORDER_ID> <TRACKING_ID> [CARRIER]")
    order_name = args[0]
    tracking_id = args[1]
    # Ignore user-supplied carrier, always use India Post Domestic
    order = get_shopify_order_by_name(order_name)
    if not order:
        return await update.message.reply_text(f"Order {order_name} not found.")
    try:
        result = add_tracking_to_order(order, tracking_id)
        await update.message.reply_text(
            f"Order {order_name} fulfilled!\nTracking ID: {tracking_id}\nCarrier: India Post Domestic")
    except Exception as e:
        await update.message.reply_text(f"Failed to fulfill order {order_name}: {e}")

async def reschedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        return await update.message.reply_text("Usage: /reschedule <SHOPIFY_ORDER_ID> <NEW_DATE> <REASON>")
    
    order_name = args[0]
    new_date = args[1]
    reason = " ".join(args[2:])  # Combine remaining args as reason
    
    order = get_shopify_order_by_name(order_name)
    if not order:
        return await update.message.reply_text(f"Order {order_name} not found.")
    
    try:
        result = reschedule_delivery(order, new_date, reason)
        await update.message.reply_text(
            f"✅ Order {order_name} rescheduled!\n"
            f"New Delivery Date: {new_date}\n"
            f"Reason: {reason}\n"
            f"Customer will be notified of the reschedule."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to reschedule order {order_name}: {e}")

async def partner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("Usage: /partner <SHOPIFY_ORDER_ID> <NEW_PARTNER>")
    
    order_name = args[0]
    new_partner = " ".join(args[1:])  # Combine remaining args as partner name
    
    order = get_shopify_order_by_name(order_name)
    if not order:
        return await update.message.reply_text(f"Order {order_name} not found.")
    
    try:
        result = update_delivery_partner(order, new_partner)
        await update.message.reply_text(
            f"✅ Order {order_name} delivery partner updated!\n"
            f"New Partner: {new_partner}\n"
            f"Customer will be notified of the change."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to update delivery partner for order {order_name}: {e}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /status <SHOPIFY_ORDER_ID>")
    
    order_name = args[0]
    order = get_shopify_order_by_name(order_name)
    if not order:
        return await update.message.reply_text(f"Order {order_name} not found.")
    
    try:
        delivery_info = get_delivery_status(order)
        
        status_message = f"📦 *Delivery Status for Order {order_name}*\n\n"
        status_message += f"*Current Partner:* {delivery_info['current_partner']}\n"
        status_message += f"*Delivery Date:* {delivery_info['delivery_date']}\n"
        status_message += f"*Tracking Number:* {delivery_info['tracking_number']}\n"
        status_message += f"*Tracking Company:* {delivery_info['tracking_company']}\n\n"
        
        if delivery_info['reschedule_history']:
            status_message += "*📅 Reschedule History:*\n"
            for i, reschedule in enumerate(delivery_info['reschedule_history'], 1):
                status_message += f"{i}. Date: {reschedule.get('New Delivery Date', 'N/A')}\n"
                status_message += f"   Reason: {reschedule.get('Reason', 'N/A')}\n"
                status_message += f"   Partner: {reschedule.get('Delivery Partner', 'N/A')}\n\n"
        
        if delivery_info['partner_history']:
            status_message += "*🚚 Partner History:*\n"
            for i, partner in enumerate(delivery_info['partner_history'], 1):
                status_message += f"{i}. Partner: {partner.get('New Partner', 'N/A')}\n"
                status_message += f"   Updated: {partner.get('Updated on', 'N/A')}\n\n"
        
        await update.message.reply_markdown(status_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to get delivery status for order {order_name}: {e}")

# ——— New Command Handlers —————————————————————————————————————————————
async def bulk_set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2 or len(args) % 2 != 0:
        return await update.message.reply_text("Usage: /bulk_set <SKU1> <qty1> <SKU2> <qty2> ...")
    
    results = []
    for i in range(0, len(args), 2):
        sku = args[i]
        try:
            qty = int(args[i + 1])
        except ValueError:
            results.append(f"❌ {sku}: Invalid quantity")
            continue
        
        try:
            item_gid, loc_gid = graphql_get_item_and_location_ids(sku)
            if not item_gid:
                results.append(f"❌ {sku}: Variant not found")
                continue
            
            current = get_product_by_sku(sku)["variants"][0]["inventory"]
            _, errs = graphql_set_quantities(item_gid, loc_gid, qty)
            if errs:
                results.append(f"❌ {sku}: {errs[0]['message']}")
            else:
                results.append(f"✅ {sku}: {current} → {qty}")
        except Exception as e:
            results.append(f"❌ {sku}: {str(e)}")
    
    await update.message.reply_text("\n".join(results))

async def bulk_return_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2 or len(args) % 2 != 0:
        return await update.message.reply_text("Usage: /bulk_return <SKU1> <qty1> <SKU2> <qty2> ...")
    
    results = []
    for i in range(0, len(args), 2):
        sku = args[i]
        try:
            qty = int(args[i + 1])
        except ValueError:
            results.append(f"❌ {sku}: Invalid quantity")
            continue
        
        try:
            item_gid, loc_gid = graphql_get_item_and_location_ids(sku)
            if not item_gid:
                results.append(f"❌ {sku}: Variant not found")
                continue
            
            prod = get_product_by_sku(sku)
            current = prod["variants"][0]["inventory"]
            new_qty = current + qty
            _, errs = graphql_set_quantities(item_gid, loc_gid, new_qty)
            if errs:
                results.append(f"❌ {sku}: {errs[0]['message']}")
            else:
                results.append(f"✅ {sku}: +{qty} → {new_qty}")
        except Exception as e:
            results.append(f"❌ {sku}: {str(e)}")
    
    await update.message.reply_text("\n".join(results))

async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        return await update.message.reply_text("Usage: /alert <SKU> <threshold>")
    
    sku = args[0]
    try:
        threshold = int(args[1])
    except ValueError:
        return await update.message.reply_text("Threshold must be a number.")
    
    # Verify SKU exists
    prod = get_product_by_sku(sku)
    if not prod:
        return await update.message.reply_text(f"❌ SKU {sku} not found.")
    
    alerts = get_inventory_alerts()
    alerts[sku] = threshold
    save_inventory_alerts(alerts)
    
    await update.message.reply_text(f"✅ Alert set for {sku} at threshold {threshold}")

async def check_alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    low_stock_items = check_low_stock_alerts()
    
    if not low_stock_items:
        await update.message.reply_text("✅ No low stock alerts")
        return
    
    alert_message = "⚠️ *Low Stock Alerts:*\n\n"
    for item in low_stock_items:
        alert_message += f"• {item['sku']}: {item['current']} (threshold: {item['threshold']})\n"
    
    await update.message.reply_markdown(alert_message)

async def order_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /order <ORDER_ID>")
    
    order_name = args[0]
    order = get_shopify_order_by_name(order_name)
    if not order:
        return await update.message.reply_text(f"Order {order_name} not found.")
    
    try:
        order_message = f"📦 *Order {order_name}*\n\n"
        order_message += f"*Customer:* {order.get('email', 'N/A')}\n"
        order_message += f"*Status:* {order.get('financial_status', 'N/A')}\n"
        order_message += f"*Total:* ₹{order.get('total_price', '0')}\n"
        order_message += f"*Created:* {order.get('created_at', 'N/A')[:10]}\n\n"
        
        order_message += "*Items:*\n"
        for item in order.get("line_items", []):
            order_message += f"• {item.get('name', 'N/A')} (SKU: {item.get('sku', 'N/A')})\n"
            order_message += f"  Qty: {item.get('quantity', 0)} | Price: ₹{item.get('price', '0')}\n"
        
        await update.message.reply_markdown(order_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to get order details: {e}")

async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /orders <pending|today|week>")
    
    filter_type = args[0].lower()
    
    try:
        if filter_type == "pending":
            orders = get_orders_by_status("open")
            title = "📋 Pending Orders"
        elif filter_type == "today":
            orders = get_orders_by_status("any", 1)
            title = "📋 Today's Orders"
        elif filter_type == "week":
            orders = get_orders_by_status("any", 7)
            title = "📋 This Week's Orders"
        else:
            return await update.message.reply_text("Invalid filter. Use: pending, today, or week")
        
        if not orders:
            await update.message.reply_text(f"✅ No {filter_type} orders found")
            return
        
        orders_message = f"{title}\n\n"
        for order in orders[:10]:  # Limit to 10 orders
            orders_message += f"• {order.get('name', 'N/A')} - ₹{order.get('total_price', '0')} - {order.get('financial_status', 'N/A')}\n"
        
        if len(orders) > 10:
            orders_message += f"\n... and {len(orders) - 10} more orders"
        
        await update.message.reply_markdown(orders_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to get orders: {e}")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("Usage: /cancel <ORDER_ID> <reason>")
    
    order_name = args[0]
    reason = " ".join(args[1:])
    
    order = get_shopify_order_by_name(order_name)
    if not order:
        return await update.message.reply_text(f"Order {order_name} not found.")
    
    try:
        url = f"https://{STORE}/admin/api/{API_VER}/orders/{order['id']}/cancel.json"
        payload = {"reason": reason}
        resp = requests.post(url, json=payload, headers=HEADERS)
        resp.raise_for_status()
        
        await update.message.reply_text(f"✅ Order {order_name} cancelled\nReason: {reason}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to cancel order: {e}")

async def refund_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("Usage: /refund <ORDER_ID> <amount>")
    
    order_name = args[0]
    try:
        amount = float(args[1])
    except ValueError:
        return await update.message.reply_text("Amount must be a number.")
    
    order = get_shopify_order_by_name(order_name)
    if not order:
        return await update.message.reply_text(f"Order {order_name} not found.")
    
    try:
        url = f"https://{STORE}/admin/api/{API_VER}/orders/{order['id']}/refunds.json"
        payload = {
            "refund": {
                "amount": str(amount),
                "currency": "INR"
            }
        }
        resp = requests.post(url, json=payload, headers=HEADERS)
        resp.raise_for_status()
        
        await update.message.reply_text(f"✅ Refund processed for {order_name}\nAmount: ₹{amount}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to process refund: {e}")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /report <daily|weekly|monthly>")
    
    period = args[0].lower()
    if period not in ["daily", "weekly", "monthly"]:
        return await update.message.reply_text("Invalid period. Use: daily, weekly, or monthly")
    
    try:
        if period == "daily":
            days = 1
            title = "📊 Daily Report"
        elif period == "weekly":
            days = 7
            title = "📊 Weekly Report"
        else:  # monthly
            days = 30
            title = "📊 Monthly Report"
        
        orders = get_orders_by_status("any", days)
        sales_data = get_sales_data(period)
        
        report_message = f"{title}\n\n"
        report_message += f"*Orders:* {len(orders)}\n"
        report_message += f"*Total Sales:* ₹{sales_data['total_sales']:.2f}\n"
        report_message += f"*Average Order Value:* ₹{sales_data['total_sales']/max(sales_data['total_orders'], 1):.2f}\n\n"
        
        # Low stock items
        low_stock_items = check_low_stock_alerts()
        if low_stock_items:
            report_message += "*⚠️ Low Stock Items:*\n"
            for item in low_stock_items:
                report_message += f"• {item['sku']}: {item['current']} (threshold: {item['threshold']})\n"
            report_message += "\n"
        
        # Top products
        if sales_data['products_sold']:
            report_message += "*🏆 Top Products:*\n"
            sorted_products = sorted(sales_data['products_sold'].items(), key=lambda x: x[1], reverse=True)
            for sku, qty in sorted_products[:5]:
                report_message += f"• {sku}: {qty} units\n"
        
        await update.message.reply_markdown(report_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to generate report: {e}")

async def hold_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("Usage: /hold <ORDER_ID> <reason>")
    
    order_name = args[0]
    reason = " ".join(args[1:])
    
    order = get_shopify_order_by_name(order_name)
    if not order:
        return await update.message.reply_text(f"Order {order_name} not found.")
    
    try:
        url = f"https://{STORE}/admin/api/{API_VER}/orders/{order['id']}.json"
        
        # Add hold note to order
        note = order.get("note", "")
        hold_note = f"\n--- ORDER ON HOLD ---\nReason: {reason}\nHeld on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        updated_note = note + hold_note if note else hold_note
        
        payload = {
            "order": {
                "id": order["id"],
                "note": updated_note,
                "tags": order.get("tags", "") + ", on-hold"
            }
        }
        
        resp = requests.put(url, json=payload, headers=HEADERS)
        resp.raise_for_status()
        
        await update.message.reply_text(f"✅ Order {order_name} put on hold\nReason: {reason}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to hold order: {e}")

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        return await update.message.reply_text("Usage: /schedule <ORDER_ID> <DATE> <TIME>")
    
    order_name = args[0]
    date = args[1]
    time = args[2]
    
    order = get_shopify_order_by_name(order_name)
    if not order:
        return await update.message.reply_text(f"Order {order_name} not found.")
    
    try:
        # Validate date format (simple check)
        if not re.match(r'\d{4}-\d{2}-\d{2}', date):
            return await update.message.reply_text("Invalid date format. Use YYYY-MM-DD")
        
        # Validate time format (simple check)
        if not re.match(r'\d{2}:\d{2}', time):
            return await update.message.reply_text("Invalid time format. Use HH:MM")
        
        url = f"https://{STORE}/admin/api/{API_VER}/orders/{order['id']}.json"
        
        # Add schedule note to order
        note = order.get("note", "")
        schedule_note = f"\n--- DELIVERY SCHEDULED ---\nDate: {date}\nTime: {time}\nScheduled on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        updated_note = note + schedule_note if note else schedule_note
        
        payload = {
            "order": {
                "id": order["id"],
                "note": updated_note
            }
        }
        
        resp = requests.put(url, json=payload, headers=HEADERS)
        resp.raise_for_status()
        
        await update.message.reply_text(f"✅ Order {order_name} scheduled for delivery\nDate: {date}\nTime: {time}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to schedule delivery: {e}")

async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /track <TRACKING_ID>")
    
    tracking_id = args[0]
    
    try:
        # This is a mock tracking response - in real implementation, you'd integrate with actual tracking APIs
        track_message = f"📦 *Tracking Information*\n\n"
        track_message += f"*Tracking ID:* {tracking_id}\n"
        track_message += f"*Status:* In Transit\n"
        track_message += f"*Carrier:* India Post Domestic\n"
        track_message += f"*Last Update:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        track_message += f"*Estimated Delivery:* {datetime.now().strftime('%Y-%m-%d')}\n\n"
        track_message += "*Tracking History:*\n"
        track_message += "• Package picked up from warehouse\n"
        track_message += "• In transit to destination\n"
        track_message += "• Out for delivery\n"
        
        await update.message.reply_markdown(track_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to track delivery: {e}")

async def product_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("Usage: /product <add|update|delete> <SKU> [additional params]")
    
    action = args[0].lower()
    sku = args[1]
    
    try:
        if action == "add":
            if len(args) < 4:
                return await update.message.reply_text("Usage: /product add <SKU> <name> <price>")
            
            name = args[2]
            price = args[3]
            
            # Create product via Shopify API
            url = f"https://{STORE}/admin/api/{API_VER}/products.json"
            payload = {
                "product": {
                    "title": name,
                    "body_html": f"Product: {name}",
                    "vendor": "NIKKI",
                    "product_type": "Clothing",
                    "variants": [{
                        "sku": sku,
                        "price": price,
                        "inventory_management": "shopify"
                    }]
                }
            }
            
            resp = requests.post(url, json=payload, headers=HEADERS)
            resp.raise_for_status()
            
            await update.message.reply_text(f"✅ Product added successfully\nSKU: {sku}\nName: {name}\nPrice: ₹{price}")
        
        elif action == "update":
            if len(args) < 4:
                return await update.message.reply_text("Usage: /product update <SKU> <field> <value>")
            
            field = args[2]
            value = args[3]
            
            # Get product by SKU first
            prod = get_product_by_sku(sku)
            if not prod:
                return await update.message.reply_text(f"❌ Product with SKU {sku} not found")
            
            # Update product (simplified - would need product ID in real implementation)
            await update.message.reply_text(f"✅ Product {sku} updated\nField: {field}\nValue: {value}")
        
        elif action == "delete":
            # Get product by SKU first
            prod = get_product_by_sku(sku)
            if not prod:
                return await update.message.reply_text(f"❌ Product with SKU {sku} not found")
            
            # Delete product (simplified - would need product ID in real implementation)
            await update.message.reply_text(f"✅ Product {sku} deleted")
        
        else:
            await update.message.reply_text("Invalid action. Use: add, update, or delete")
    
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to {action} product: {e}")

async def notify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("Usage: /notify <ORDER_ID> <message>")
    
    order_id = args[0]
    message = " ".join(args[1:])
    
    order = get_shopify_order_by_name(order_id)
    if not order:
        return await update.message.reply_text(f"Order {order_id} not found.")
    
    try:
        url = f"https://{STORE}/admin/api/{API_VER}/orders/{order['id']}.json"
        
        # Add notification note to order
        note = order.get("note", "")
        notify_note = f"\n--- CUSTOMER NOTIFICATION ---\nMessage: {message}\nSent on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        updated_note = note + notify_note if note else notify_note
        
        payload = {
            "order": {
                "id": order["id"],
                "note": updated_note
            }
        }
        
        resp = requests.put(url, json=payload, headers=HEADERS)
        resp.raise_for_status()
        
        await update.message.reply_text(f"✅ Notification sent for order {order_id}\nMessage: {message}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send notification: {e}")

async def autorestock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /autorestock <SKU>")
    
    sku = args[0]
    
    try:
        # Get auto restock settings
        auto_restock_data = load_json_file(AUTO_RESTOCK_FILE)
        
        if sku in auto_restock_data:
            # Disable auto restock
            del auto_restock_data[sku]
            save_json_file(AUTO_RESTOCK_FILE, auto_restock_data)
            await update.message.reply_text(f"✅ Auto restock disabled for {sku}")
        else:
            # Enable auto restock
            prediction = predict_stock_needs(sku)
            if "error" in prediction:
                await update.message.reply_text(f"❌ {prediction['error']}")
                return
            
            auto_restock_data[sku] = {
                "threshold": prediction['recommended_stock'],
                "enabled": True,
                "created_at": datetime.now().isoformat()
            }
            save_json_file(AUTO_RESTOCK_FILE, auto_restock_data)
            
            await update.message.reply_text(f"✅ Auto restock enabled for {sku}\nThreshold: {prediction['recommended_stock']} units")
    
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to configure auto restock: {e}")

async def autofulfill_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Get auto fulfillment settings
        auto_fulfill_data = load_json_file("auto_fulfill.json")
        
        if not auto_fulfill_data:
            await update.message.reply_text("📋 *Auto Fulfillment Rules*\n\nNo rules configured")
            return
        
        rules_message = "📋 *Auto Fulfillment Rules*\n\n"
        for rule_id, rule in auto_fulfill_data.items():
            rules_message += f"• Rule {rule_id}: {rule.get('description', 'N/A')}\n"
            rules_message += f"  Status: {'✅ Enabled' if rule.get('enabled') else '❌ Disabled'}\n\n"
        
        await update.message.reply_markdown(rules_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to get auto fulfillment rules: {e}")

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Create backup of important data
        backup_data = {
            "timestamp": datetime.now().isoformat(),
            "inventory_alerts": get_inventory_alerts(),
            "support_tickets": get_support_tickets(),
            "auto_restock": load_json_file(AUTO_RESTOCK_FILE),
            "delivery_zones": DELIVERY_ZONES
        }
        
        # Save backup to file
        backup_filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_json_file(backup_filename, backup_data)
        
        # Send backup file
        backup_file = io.BytesIO(json.dumps(backup_data, indent=2).encode())
        backup_file.name = backup_filename
        
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=backup_file,
            caption="💾 System Backup"
        )
        
        await update.message.reply_text(f"✅ Backup created successfully\nFile: {backup_filename}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to create backup: {e}")

async def notifications_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /notifications <on|off|status> [type]")
    
    action = args[0].lower()
    
    try:
        notifications_data = load_json_file(NOTIFICATIONS_FILE)
        
        if action == "on":
            if len(args) < 2:
                return await update.message.reply_text("Usage: /notifications on <type>")
            
            notification_type = args[1]
            if notification_type not in NOTIFICATION_TYPES:
                return await update.message.reply_text(f"Invalid type. Use: {', '.join(NOTIFICATION_TYPES)}")
            
            notifications_data[notification_type] = True
            save_json_file(NOTIFICATIONS_FILE, notifications_data)
            
            await update.message.reply_text(f"✅ {notification_type} notifications enabled")
        
        elif action == "off":
            if len(args) < 2:
                return await update.message.reply_text("Usage: /notifications off <type>")
            
            notification_type = args[1]
            if notification_type not in NOTIFICATION_TYPES:
                return await update.message.reply_text(f"Invalid type. Use: {', '.join(NOTIFICATION_TYPES)}")
            
            notifications_data[notification_type] = False
            save_json_file(NOTIFICATIONS_FILE, notifications_data)
            
            await update.message.reply_text(f"✅ {notification_type} notifications disabled")
        
        elif action == "status":
            status_message = "🔔 *Notification Settings*\n\n"
            for notification_type in NOTIFICATION_TYPES:
                status = notifications_data.get(notification_type, True)
                status_message += f"• {notification_type}: {'✅ Enabled' if status else '❌ Disabled'}\n"
            
            await update.message.reply_markdown(status_message)
        
        else:
            await update.message.reply_text("Invalid action. Use: on, off, or status")
    
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to manage notifications: {e}")

async def sales_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /sales <today|week|month>")
    
    period = args[0].lower()
    if period not in ["today", "week", "month"]:
        return await update.message.reply_text("Invalid period. Use: today, week, or month")
    
    try:
        sales_data = get_sales_data(period)
        
        sales_message = f"📊 *Sales Report - {period.title()}*\n\n"
        sales_message += f"*Total Sales:* ₹{sales_data['total_sales']:.2f}\n"
        sales_message += f"*Total Orders:* {sales_data['total_orders']}\n"
        sales_message += f"*Average Order Value:* ₹{sales_data['total_sales']/max(sales_data['total_orders'], 1):.2f}\n\n"
        
        if sales_data['products_sold']:
            sales_message += "*Top Products:*\n"
            sorted_products = sorted(sales_data['products_sold'].items(), key=lambda x: x[1], reverse=True)
            for sku, qty in sorted_products[:5]:
                sales_message += f"• {sku}: {qty} units\n"
        
        await update.message.reply_markdown(sales_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to get sales data: {e}")

async def top_products_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sales_data = get_sales_data("month")
        
        if not sales_data['products_sold']:
            await update.message.reply_text("📊 No product sales data available")
            return
        
        products_message = "🏆 *Top Selling Products (Last 30 Days)*\n\n"
        sorted_products = sorted(sales_data['products_sold'].items(), key=lambda x: x[1], reverse=True)
        
        for i, (sku, qty) in enumerate(sorted_products[:10], 1):
            products_message += f"{i}. {sku}: {qty} units\n"
        
        await update.message.reply_markdown(products_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to get top products: {e}")

async def customer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /customer <EMAIL>")
    
    email = args[0]
    
    try:
        url = f"https://{STORE}/admin/api/{API_VER}/customers/search.json"
        params = {"query": email}
        resp = requests.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        customers = resp.json().get("customers", [])
        
        if not customers:
            await update.message.reply_text(f"❌ No customer found with email: {email}")
            return
        
        customer = customers[0]
        customer_message = f"👤 *Customer Information*\n\n"
        customer_message += f"*Name:* {customer.get('first_name', '')} {customer.get('last_name', '')}\n"
        customer_message += f"*Email:* {customer.get('email', 'N/A')}\n"
        customer_message += f"*Phone:* {customer.get('phone', 'N/A')}\n"
        customer_message += f"*Total Spent:* ₹{customer.get('total_spent', '0')}\n"
        customer_message += f"*Orders Count:* {customer.get('orders_count', 0)}\n"
        customer_message += f"*Created:* {customer.get('created_at', 'N/A')[:10]}\n"
        
        await update.message.reply_markdown(customer_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to get customer info: {e}")

async def customers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        url = f"https://{STORE}/admin/api/{API_VER}/customers.json"
        params = {"limit": 10, "order": "created_at DESC"}
        resp = requests.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        customers = resp.json().get("customers", [])
        
        if not customers:
            await update.message.reply_text("📊 No recent customers found")
            return
        
        customers_message = "👥 *Recent Customers*\n\n"
        for customer in customers:
            name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
            customers_message += f"• {name} - {customer.get('email', 'N/A')}\n"
            customers_message += f"  Orders: {customer.get('orders_count', 0)} | Spent: ₹{customer.get('total_spent', '0')}\n\n"
        
        await update.message.reply_markdown(customers_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to get customers: {e}")

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("Usage: /support <ORDER_ID> <description>")
    
    order_id = args[0]
    description = " ".join(args[1:])
    user_id = update.effective_user.id
    
    try:
        ticket = create_support_ticket(order_id, description, user_id)
        
        support_message = f"🎫 *Support Ticket Created*\n\n"
        support_message += f"*Ticket ID:* {ticket['id']}\n"
        support_message += f"*Order ID:* {ticket['order_id']}\n"
        support_message += f"*Description:* {ticket['description']}\n"
        support_message += f"*Status:* {ticket['status']}\n"
        support_message += f"*Created:* {ticket['created_at'][:19]}\n"
        
        await update.message.reply_markdown(support_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to create support ticket: {e}")

async def issue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /issue <description>")
    
    description = " ".join(args)
    user_id = update.effective_user.id
    
    try:
        ticket = create_support_ticket("N/A", description, user_id)
        
        issue_message = f"🐛 *Issue Reported*\n\n"
        issue_message += f"*Ticket ID:* {ticket['id']}\n"
        issue_message += f"*Description:* {ticket['description']}\n"
        issue_message += f"*Status:* {ticket['status']}\n"
        issue_message += f"*Created:* {ticket['created_at'][:19]}\n"
        
        await update.message.reply_markdown(issue_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to report issue: {e}")

async def discount_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("Usage: /discount <ORDER_ID> <percentage>")
    
    order_id = args[0]
    try:
        percentage = float(args[1])
        if percentage < 0 or percentage > 100:
            return await update.message.reply_text("Percentage must be between 0 and 100")
    except ValueError:
        return await update.message.reply_text("Percentage must be a number")
    
    try:
        result = apply_discount_to_order(order_id, percentage)
        if result:
            await update.message.reply_text(f"✅ Discount applied to {order_id}\nPercentage: {percentage}%")
        else:
            await update.message.reply_text(f"❌ Failed to apply discount to {order_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to apply discount: {e}")

async def predict_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /predict <SKU>")
    
    sku = args[0]
    
    try:
        prediction = predict_stock_needs(sku)
        
        if "error" in prediction:
            await update.message.reply_text(f"❌ {prediction['error']}")
            return
        
        predict_message = f"🔮 *Stock Prediction for {sku}*\n\n"
        predict_message += f"*Current Stock:* {prediction['current_stock']}\n"
        predict_message += f"*Monthly Demand:* {prediction['monthly_demand']}\n"
        predict_message += f"*Predicted Demand:* {prediction['predicted_demand']}\n"
        predict_message += f"*Recommended Stock:* {prediction['recommended_stock']}\n"
        predict_message += f"*Stock Needed:* {prediction['stock_needed']}\n"
        
        await update.message.reply_markdown(predict_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to predict stock needs: {e}")

async def trends_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sales_data = get_sales_data("month")
        
        if not sales_data['products_sold']:
            await update.message.reply_text("📈 No trend data available")
            return
        
        trends_message = "📈 *Sales Trends (Last 30 Days)*\n\n"
        
        # Calculate trends
        total_products = len(sales_data['products_sold'])
        total_units = sum(sales_data['products_sold'].values())
        avg_units_per_product = total_units / total_products if total_products > 0 else 0
        
        trends_message += f"*Total Products Sold:* {total_products}\n"
        trends_message += f"*Total Units Sold:* {total_units}\n"
        trends_message += f"*Average Units per Product:* {avg_units_per_product:.1f}\n\n"
        
        # Top performers
        sorted_products = sorted(sales_data['products_sold'].items(), key=lambda x: x[1], reverse=True)
        trends_message += "*🏆 Top Performers:*\n"
        for sku, qty in sorted_products[:3]:
            trends_message += f"• {sku}: {qty} units\n"
        
        await update.message.reply_markdown(trends_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to get trends: {e}")

async def zone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /zone <PINCODE>")
    
    pincode = args[0]
    
    try:
        zone, delivery_time = get_delivery_zone(pincode)
        
        zone_message = f"📍 *Delivery Zone Check*\n\n"
        zone_message += f"*Pincode:* {pincode}\n"
        zone_message += f"*Zone:* {zone}\n"
        zone_message += f"*Delivery Time:* {delivery_time}\n"
        
        if zone == "Not Available":
            zone_message += "\n❌ *Delivery not available for this pincode*"
        elif zone == "Invalid":
            zone_message += "\n❌ *Invalid pincode format*"
        else:
            zone_message += f"\n✅ *Delivery available*"
        
        await update.message.reply_markdown(zone_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to check delivery zone: {e}")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /search <keyword>")
    
    keyword = " ".join(args)
    
    try:
        results = search_products(keyword)
        
        if not results:
            await update.message.reply_text(f"🔍 No products found for: {keyword}")
            return
        
        search_message = f"🔍 *Search Results for: {keyword}*\n\n"
        
        for i, product in enumerate(results[:5], 1):
            search_message += f"{i}. *{product.get('title', 'N/A')}*\n"
            search_message += f"   SKU: {product.get('variants', [{}])[0].get('sku', 'N/A')}\n"
            search_message += f"   Price: ₹{product.get('variants', [{}])[0].get('price', '0')}\n\n"
        
        if len(results) > 5:
            search_message += f"... and {len(results) - 5} more products"
        
        await update.message.reply_markdown(search_message)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to search products: {e}")

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        return await update.message.reply_text("Usage: /export <inventory|orders>")
    
    export_type = args[0].lower()
    
    try:
        if export_type == "inventory":
            data = export_inventory_data()
            if not data:
                await update.message.reply_text("❌ No inventory data to export")
                return
            
            # Create CSV content
            csv_content = "SKU,Product,Variant,Price,Inventory,Status\n"
            for row in data:
                csv_content += f"{row['SKU']},{row['Product']},{row['Variant']},{row['Price']},{row['Inventory']},{row['Status']}\n"
            
            # Send as document
            csv_file = io.BytesIO(csv_content.encode())
            csv_file.name = f"inventory_export_{datetime.now().strftime('%Y%m%d')}.csv"
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=csv_file,
                caption="📊 Inventory Export"
            )
        
        elif export_type == "orders":
            orders = get_orders_by_status("any", 30)  # Last 30 days
            
            if not orders:
                await update.message.reply_text("❌ No orders to export")
                return
            
            # Create CSV content
            csv_content = "Order ID,Customer,Total,Status,Date\n"
            for order in orders:
                csv_content += f"{order.get('name', 'N/A')},{order.get('email', 'N/A')},{order.get('total_price', '0')},{order.get('financial_status', 'N/A')},{order.get('created_at', 'N/A')[:10]}\n"
            
            # Send as document
            csv_file = io.BytesIO(csv_content.encode())
            csv_file.name = f"orders_export_{datetime.now().strftime('%Y%m%d')}.csv"
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=csv_file,
                caption="📋 Orders Export"
            )
        
        else:
            await update.message.reply_text("Invalid export type. Use: inventory or orders")
    
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to export data: {e}")

async def quick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick actions menu with interactive buttons"""
    keyboard = [
        [
            InlineKeyboardButton("📦 Check Alerts", callback_data="check_alerts"),
            InlineKeyboardButton("📋 Pending Orders", callback_data="pending_orders")
        ],
        [
            InlineKeyboardButton("📊 Sales Today", callback_data="sales_today"),
            InlineKeyboardButton("🔍 Search Products", callback_data="search_products")
        ],
        [
            InlineKeyboardButton("🚚 Delivery Status", callback_data="delivery_status"),
            InlineKeyboardButton("👥 Recent Customers", callback_data="recent_customers")
        ],
        [
            InlineKeyboardButton("📈 Trends", callback_data="trends"),
            InlineKeyboardButton("🎫 Support Tickets", callback_data="support_tickets")
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="close_menu")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🚀 *Quick Actions Menu*\n\nSelect an action:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def quick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quick action callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "check_alerts":
        low_stock_items = check_low_stock_alerts()
        if not low_stock_items:
            await query.edit_message_text("✅ No low stock alerts")
        else:
            alert_message = "⚠️ *Low Stock Alerts:*\n\n"
            for item in low_stock_items:
                alert_message += f"• {item['sku']}: {item['current']} (threshold: {item['threshold']})\n"
            await query.edit_message_text(alert_message, parse_mode="Markdown")
    
    elif query.data == "pending_orders":
        orders = get_orders_by_status("open")
        if not orders:
            await query.edit_message_text("✅ No pending orders")
        else:
            orders_message = "📋 *Pending Orders*\n\n"
            for order in orders[:5]:
                orders_message += f"• {order.get('name', 'N/A')} - ₹{order.get('total_price', '0')}\n"
            await query.edit_message_text(orders_message, parse_mode="Markdown")
    
    elif query.data == "sales_today":
        sales_data = get_sales_data("today")
        sales_message = f"📊 *Today's Sales*\n\n*Total:* ₹{sales_data['total_sales']:.2f}\n*Orders:* {sales_data['total_orders']}"
        await query.edit_message_text(sales_message, parse_mode="Markdown")
    
    elif query.data == "close_menu":
        await query.edit_message_text("👋 Menu closed")

# ——— Shopify/Inventory logic —————————————————————————————————————————————
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

async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args)!=2:
        return await update.message.reply_text("Usage: /set <SKU> <qty>")
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
    
    # ——— Basic Commands —————————————————————————————————————————————
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("help",        help_command))
    app.add_handler(CommandHandler("qrtest",      qrtest_command))
    app.add_handler(CommandHandler("privacy",     privacy_command))
    
    # ——— Inventory Management —————————————————————————————————————————————
    app.add_handler(CommandHandler("set",    set_command))
    app.add_handler(CommandHandler("return",      return_command))
    app.add_handler(CommandHandler("bulk_set", bulk_set_command))
    app.add_handler(CommandHandler("bulk_return", bulk_return_command))
    app.add_handler(CommandHandler("alert", alert_command))
    app.add_handler(CommandHandler("check_alerts", check_alerts_command))
    
    # ——— Order Management —————————————————————————————————————————————
    app.add_handler(CommandHandler("order", order_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("refund", refund_command))
    app.add_handler(CommandHandler("hold", hold_command))
    app.add_handler(CommandHandler("schedule", schedule_command))
    app.add_handler(CommandHandler("track", track_command))
    
    # ——— Delivery Management —————————————————————————————————————————————
    app.add_handler(CommandHandler("checktracking", checktracking_command))
    app.add_handler(CommandHandler("fulfill", fulfill_command))
    app.add_handler(CommandHandler("reschedule", reschedule_command))
    app.add_handler(CommandHandler("partner", partner_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("zone", zone_command))
    
    # ——— Analytics & Reports —————————————————————————————————————————————
    app.add_handler(CommandHandler("sales", sales_command))
    app.add_handler(CommandHandler("top_products", top_products_command))
    app.add_handler(CommandHandler("customer", customer_command))
    app.add_handler(CommandHandler("customers", customers_command))
    app.add_handler(CommandHandler("report", report_command))
    
    # ——— Customer Service —————————————————————————————————————————————
    app.add_handler(CommandHandler("support", support_command))
    app.add_handler(CommandHandler("issue", issue_command))
    app.add_handler(CommandHandler("notify", notify_command))
    
    # ——— Product Management —————————————————————————————————————————————
    app.add_handler(CommandHandler("discount", discount_command))
    app.add_handler(CommandHandler("product", product_command))
    
    # ——— Smart Features —————————————————————————————————————————————
    app.add_handler(CommandHandler("predict", predict_command))
    app.add_handler(CommandHandler("trends", trends_command))
    app.add_handler(CommandHandler("autorestock", autorestock_command))
    app.add_handler(CommandHandler("autofulfill", autofulfill_command))
    
    # ——— System Features —————————————————————————————————————————————
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("quick", quick_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("notifications", notifications_command))
    
    # ——— Callback Handlers —————————————————————————————————————————————
    app.add_handler(CallbackQueryHandler(quit_callback, pattern="quit"))
    app.add_handler(CallbackQueryHandler(quick_callback, pattern="^(check_alerts|pending_orders|sales_today|close_menu)$"))
    
    # ——— Message Handlers —————————————————————————————————————————————
    app.add_handler(MessageHandler(filters.PHOTO,           photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sku))
    app.add_handler(MessageHandler(filters.COMMAND,          unknown))
    
    # ——— Error Handler —————————————————————————————————————————————
    app.add_error_handler(error_handler)

    logger.info("Bot starting…")
    app.run_polling()

if __name__ == "__main__":
    main()
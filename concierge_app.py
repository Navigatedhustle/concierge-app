# Restaurant & Travel Concierge Meal Generator (Render-safe build)
# - Standalone templates (no {% extends %})
# - Headless HTML writer doesn't use Flask context
# - PDF export with ReportLab
# - Optional CSP header for embedding in GHL (edit domain below)

from __future__ import annotations
import os, json, random, argparse, datetime, pathlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, request, render_template_string, send_from_directory, make_response

# Try optional PDF deps
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

APP_NAME = "Concierge Meal Generator"
app = Flask(__name__)

# ---- Embed header (set your membership domain here) ----
@app.after_request
def add_embed_headers(resp):
    # Example:
    # resp.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://members.yourdomain.com"
    return resp

# ---------- MENU LOADING ----------
import csv, io

MENU_PATH = os.environ.get("MENU_PATH", "data/menu.json")  # local file in repo
MENU_CSV_URL = os.environ.get("MENU_CSV_URL")              # published CSV URL (optional)
ADMIN_RELOAD_KEY = os.environ.get("ADMIN_RELOAD_KEY", "change-me")

def _coerce_item(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate & coerce one item. Return None if invalid."""
    required = ["name","chain","cuisine","K","P","C","F"]
    if not all(k in d and str(d[k]).strip() != "" for k in required):
        return None
    try:
        d["K"] = int(float(d["K"])); d["P"] = int(float(d["P"]))
        d["C"] = int(float(d["C"])); d["F"] = int(float(d["F"]))
    except Exception:
        return None
    # optional fields
    d["meal_type"] = (d.get("meal_type") or "").lower() or None
    if isinstance(d.get("tags"), str):
        d["tags"] = [t.strip() for t in d["tags"].split(",") if t.strip()]
    elif not isinstance(d.get("tags"), list):
        d["tags"] = []
    return d

def load_menu_from_json(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path): return []
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    items = raw["items"] if isinstance(raw, dict) and "items" in raw else raw
    out = []
    for x in items:
        x = _coerce_item(x)
        if x: out.append(x)
    return out

def load_menu_from_csv_text(csv_text: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    out = []
    for row in reader:
        item = _coerce_item(row)
        if item: out.append(item)
    return out

def load_menu() -> List[Dict[str, Any]]:
    # 1) If a CSV URL is set, try pull it
    if MENU_CSV_URL:
        try:
            import requests
            r = requests.get(MENU_CSV_URL, timeout=10)
            if r.ok and r.text.strip():
                data = load_menu_from_csv_text(r.text)
                if data: return data
        except Exception:
            pass  # fall back
    # 2) local JSON file if present
    data = load_menu_from_json(MENU_PATH)
    return data  # may be [] if none found

def merged_menu(seed: List[Dict[str, Any]], external: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Seed + external (external wins on exact (chain,name) duplicates)."""
    key = lambda x: (x["chain"].lower(), x["name"].lower())
    seen = {}
    for x in seed: seen[key(x)] = x
    for x in external: seen[key(x)] = x
    return list(seen.values())

# -----------------------------
# Seed menu (expand as you like)
# -----------------------------
SEED_MENU: List[Dict[str, Any]] = [
    {"name":"Burrito Bowl: chicken, fajita veg, brown rice (light), pico, salsa, lettuce", "chain":"Chipotle","cuisine":"Mexican","K":540,"P":48,"C":58,"F":14},
    {"name":"Salad Bowl: steak, black beans, pico, tomatillo salsa", "chain":"Chipotle","cuisine":"Mexican","K":430,"P":42,"C":33,"F":14},
    {"name":"Grilled Nuggets (12 ct) + Side Salad (lite dressing)", "chain":"Chick-fil-A","cuisine":"American","K":360,"P":46,"C":18,"F":12},
    {"name":"Egg White & Roasted Red Pepper Egg Bites", "chain":"Starbucks","cuisine":"Cafe","K":170,"P":13,"C":11,"F":7},
    {"name":"6\" Turkey on wheat, double meat, loaded veg, no cheese", "chain":"Subway","cuisine":"Sandwiches","K":420,"P":34,"C":54,"F":8},
    {"name":"Bowl: Grilled Teriyaki Chicken + Super Greens", "chain":"Panda Express","cuisine":"Chinese","K":420,"P":36,"C":26,"F":18},
    {"name":"Footlong Turkey (double meat) on wheat, cheese, full condiments", "chain":"Subway","cuisine":"Sandwiches","K":720,"P":55,"C":78,"F":20},
    {"name":"Orange Chicken + Super Greens (plate) + extra chicken", "chain":"Panda Express","cuisine":"Chinese","K":780,"P":45,"C":75,"F":30},
    {"name":"Grilled Chicken Club Sandwich + small fries", "chain":"Chick-fil-A","cuisine":"American","K":830,"P":44,"C":74,"F":39},
    {"name":"Protein smoothie: whey double scoop + peanut butter + banana + oats (16 oz)", "chain":"Grocery","cuisine":"Any","K":700,"P":55,"C":70,"F":22},
    {"name":"Lifestyle Bowl: double chicken, white rice, black beans, tomatillo, lettuce, guac", "chain":"Chipotle","cuisine":"Mexican","K":760,"P":65,"C":66,"F":24},
    {"name":"Steak Bowl: extra steak, white rice, fajita veggies, mild salsa", "chain":"Chipotle","cuisine":"Mexican","K":700,"P":55,"C":60,"F":22},
    {"name":"Keto Bowl: double chicken, fajita veg, cheese, sour cream (no rice/beans)", "chain":"Chipotle","cuisine":"Mexican","K":520,"P":60,"C":16,"F":22},

    {"name":"Grilled Chicken Sandwich + Fruit Cup", "chain":"Chick-fil-A","cuisine":"American","K":520,"P":35,"C":65,"F":10},
    {"name":"Cobb Salad (grilled) + lite dressing", "chain":"Chick-fil-A","cuisine":"American","K":510,"P":40,"C":28,"F":24},
    {"name":"12ct Grilled Nuggets + Greek Yogurt Parfait", "chain":"Chick-fil-A","cuisine":"American","K":540,"P":52,"C":45,"F":12},

    {"name":"Protein Oatmeal: oatmeal + whey packet + banana", "chain":"Starbucks","cuisine":"Cafe","K":560,"P":32,"C":82,"F":12},
    {"name":"Turkey Bacon Cheddar Egg White Sandwich + plain oatmeal", "chain":"Starbucks","cuisine":"Cafe","K":530,"P":30,"C":65,"F":14},
    {"name":"Double-Smoked Bacon & Cheddar Sandwich", "chain":"Starbucks","cuisine":"Cafe","K":500,"P":25,"C":45,"F":25},

    {"name":"Footlong Rotisserie Chicken, no mayo", "chain":"Subway","cuisine":"Sandwiches","K":760,"P":60,"C":86,"F":16},
    {"name":"Protein Bowl: double chicken + extra veg", "chain":"Subway","cuisine":"Sandwiches","K":480,"P":60,"C":20,"F":14},

    {"name":"Plate: Grilled Teriyaki Chicken + Super Greens + Mushroom Chicken", "chain":"Panda Express","cuisine":"Chinese","K":780,"P":54,"C":45,"F":32},
    {"name":"Bowl: Shanghai Angus Steak + Super Greens", "chain":"Panda Express","cuisine":"Chinese","K":520,"P":26,"C":30,"F":24},
    {"name":"Orange Chicken (1 entree) + Super Greens bowl", "chain":"Panda Express","cuisine":"Chinese","K":600,"P":26,"C":46,"F":28},

    {"name":"Power Menu Bowl (Chicken)", "chain":"Taco Bell","cuisine":"Mexican","K":480,"P":26,"C":50,"F":17},
    {"name":"2x Chicken Soft Taco (fresco) + Bean Burrito (fresco)", "chain":"Taco Bell","cuisine":"Mexican","K":820,"P":40,"C":110,"F":22},

    {"name":"Burrito Bowl: double chicken, rice + beans, salsa, lettuce", "chain":"QDOBA","cuisine":"Mexican","K":780,"P":65,"C":70,"F":22},
    {"name":"Chicken Burrito (no queso) + extra chicken", "chain":"QDOBA","cuisine":"Mexican","K":790,"P":60,"C":84,"F":20},

    {"name":"Quarter Pounder (no cheese) + side salad (no dressing)", "chain":"McDonald's","cuisine":"American","K":530,"P":30,"C":40,"F":25},
    {"name":"2x Egg McMuffin (no cheese)", "chain":"McDonald's","cuisine":"American","K":500,"P":32,"C":60,"F":18},
    {"name":"McDouble + apple slices", "chain":"McDonald's","cuisine":"American","K":460,"P":24,"C":44,"F":20},

    {"name":"Grilled Chicken Sandwich + plain baked potato", "chain":"Wendy's","cuisine":"American","K":680,"P":45,"C":93,"F":12},
    {"name":"Large Chili + Grilled Chicken Wrap", "chain":"Wendy's","cuisine":"American","K":670,"P":52,"C":63,"F":19},

    {"name":"Green Goddess Cobb with Chicken (full)", "chain":"Panera","cuisine":"American","K":500,"P":40,"C":30,"F":23},
    {"name":"Turkey Avocado BLT (half) + Turkey Chili (cup)", "chain":"Panera","cuisine":"American","K":720,"P":45,"C":60,"F":28},

    {"name":"Grilled Chicken breast + corn + green beans", "chain":"KFC","cuisine":"American","K":460,"P":50,"C":45,"F":9},
    {"name":"Blackened Tenders (5) + Red Beans & Rice", "chain":"Popeyes","cuisine":"American","K":610,"P":45,"C":54,"F":20},

    {"name":"Single ShackBurger + side salad", "chain":"Shake Shack","cuisine":"American","K":700,"P":33,"C":48,"F":40},
    {"name":"Little Hamburger + small fries (shared half)", "chain":"Five Guys","cuisine":"American","K":900,"P":35,"C":60,"F":50},

    {"name":"Hot Bar: grilled salmon (8 oz) + brown rice cup + broccoli", "chain":"Whole Foods","cuisine":"Any","K":750,"P":50,"C":60,"F":24},
    {"name":"Chicken Avocado Salad + Greek yogurt", "chain":"Pret a Manger","cuisine":"Cafe","K":620,"P":38,"C":40,"F":26},

    {"name":"Protein Smoothie: whey double scoop + peanut butter + banana + oats", "chain":"Grocery","cuisine":"Any","K":700,"P":55,"C":70,"F":22},
    {"name":"Greek yogurt (2 cups) + 1/2 cup granola + 1 tbsp honey", "chain":"Grocery","cuisine":"Any","K":610,"P":40,"C":80,"F":12},
    {"name":"Cottage cheese (2 cups) + berries + mixed nuts (1 oz)", "chain":"Grocery","cuisine":"Any","K":520,"P":45,"C":40,"F":18},
    {"name":"Rotisserie chicken (10 oz) + microwave potato", "chain":"Grocery","cuisine":"Any","K":680,"P":75,"C":50,"F":18},
    {"name":"2 cans tuna + avocado + 2 whole-wheat wraps", "chain":"Grocery","cuisine":"Any","K":640,"P":55,"C":50,"F":22},
    {"name":"Jerky (3 oz) + trail mix (1 oz) + apple", "chain":"Grocery","cuisine":"Any","K":520,"P":35,"C":50,"F":18},
    {"name":"Protein oatmeal: oats + whey + peanut butter", "chain":"Grocery","cuisine":"Any","K":560,"P":40,"C":55,"F":16},
    {"name":"High-protein frozen burrito", "chain":"Grocery","cuisine":"Any","K":450,"P":33,"C":50,"F":12},
    {"name":"Sushi: 2x spicy tuna rolls", "chain":"Grocery","cuisine":"Any","K":640,"P":34,"C":80,"F":18},

    {"name":"Fairlife 42g shake + 2 bananas + nut pack (1 oz)", "chain":"Gas Station","cuisine":"Any","K":600,"P":42,"C":95,"F":15},

    {"name":"Egg-white veggie omelette + fruit + dry toast", "chain":"IHOP","cuisine":"American","K":620,"P":45,"C":68,"F":14},
    {"name":"Fit Slam: egg whites + turkey bacon + English muffin + fruit", "chain":"Denny's","cuisine":"American","K":650,"P":40,"C":70,"F":20},
        # ---- High-calorie additions ----
    {"name":"Double Chicken Burrito + rice, beans, queso, guac", "chain":"Chipotle","cuisine":"Mexican","K":1150,"P":72,"C":108,"F":42},
    {"name":"Double Steak Bowl + white rice, black beans, queso, guac", "chain":"Chipotle","cuisine":"Mexican","K":1000,"P":66,"C":86,"F":35},
    {"name":"Carnitas Burrito + queso + guac", "chain":"Chipotle","cuisine":"Mexican","K":1200,"P":52,"C":110,"F":55},
    {"name":"Chicken Quesadilla (large) + guac", "chain":"Chipotle","cuisine":"Mexican","K":900,"P":55,"C":60,"F":45},
    {"name":"Burrito Bowl: double chicken, double rice, beans, queso", "chain":"Chipotle","cuisine":"Mexican","K":1050,"P":70,"C":115,"F":28},

    {"name":"Spicy Deluxe Sandwich + medium waffle fries", "chain":"Chick-fil-A","cuisine":"American","K":980,"P":36,"C":96,"F":45},
    {"name":"12ct Nuggets (fried) + medium waffle fries", "chain":"Chick-fil-A","cuisine":"American","K":970,"P":44,"C":88,"F":42},
    {"name":"Grilled Chicken Sandwich + Mac & Cheese (medium)", "chain":"Chick-fil-A","cuisine":"American","K":920,"P":45,"C":92,"F":28},

    {"name":"Footlong Italian B.M.T. (double meat & cheese) on Italian", "chain":"Subway","cuisine":"Sandwiches","K":1040,"P":60,"C":96,"F":44},
    {"name":"Footlong Steak & Cheese (double meat) + full condiments", "chain":"Subway","cuisine":"Sandwiches","K":980,"P":62,"C":90,"F":32},
    {"name":"Protein Bowl: double rotisserie chicken + avocado + rice", "chain":"Subway","cuisine":"Sandwiches","K":900,"P":70,"C":60,"F":32},

    {"name":"Bigger Plate: Orange Chicken + Beijing Beef + Chow Mein", "chain":"Panda Express","cuisine":"Chinese","K":1420,"P":45,"C":150,"F":60},
    {"name":"Plate: Orange Chicken + Honey Sesame Chicken + Fried Rice", "chain":"Panda Express","cuisine":"Chinese","K":1180,"P":40,"C":130,"F":42},
    {"name":"Bowl: Shanghai Angus Steak + Chow Mein", "chain":"Panda Express","cuisine":"Chinese","K":930,"P":34,"C":96,"F":34},

    {"name":"Power Menu Bowl (Chicken) + cheesy fiesta potatoes", "chain":"Taco Bell","cuisine":"Mexican","K":820,"P":30,"C":90,"F":28},
    {"name":"Grilled Cheese Burrito (steak) + Beef Burrito", "chain":"Taco Bell","cuisine":"Mexican","K":1200,"P":55,"C":126,"F":44},

    {"name":"Burrito: extra chicken + rice + beans + queso + guac", "chain":"QDOBA","cuisine":"Mexican","K":1120,"P":62,"C":104,"F":38},
    {"name":"Burrito Bowl: double steak + queso + guac + tortilla on side", "chain":"QDOBA","cuisine":"Mexican","K":1050,"P":60,"C":95,"F":36},

    {"name":"Double Quarter Pounder w/ Cheese + medium fries", "chain":"McDonald's","cuisine":"American","K":1290,"P":63,"C":103,"F":62},
    {"name":"Big Mac + 10pc Chicken McNuggets (no fries)", "chain":"McDonald's","cuisine":"American","K":1160,"P":57,"C":96,"F":54},

    {"name":"Dave's Double + plain baked potato (butter packet)", "chain":"Wendy's","cuisine":"American","K":1210,"P":63,"C":96,"F":60},
    {"name":"Baconator (single) + medium chili", "chain":"Wendy's","cuisine":"American","K":1150,"P":64,"C":54,"F":72},

    {"name":"Chipotle Chicken Avocado Melt + Mac & Cheese (cup)", "chain":"Panera","cuisine":"American","K":1170,"P":52,"C":98,"F":56},
    {"name":"Turkey Avocado BLT (whole) + chips", "chain":"Panera","cuisine":"American","K":980,"P":45,"C":90,"F":38},

    {"name":"3pc Chicken (mixed) + mashed & gravy + biscuit", "chain":"KFC","cuisine":"American","K":1150,"P":60,"C":90,"F":55},
    {"name":"5 Blackened Tenders + large Red Beans & Rice + biscuit", "chain":"Popeyes","cuisine":"American","K":1020,"P":55,"C":98,"F":34},

    {"name":"Double ShackBurger + fries (share half)", "chain":"Shake Shack","cuisine":"American","K":1200,"P":50,"C":90,"F":65},
    {"name":"Cheeseburger + little fries (share half)", "chain":"Five Guys","cuisine":"American","K":1250,"P":45,"C":85,"F":72},

    {"name":"Hot Bar: grilled salmon (10 oz) + olive oil drizzle + rice cup", "chain":"Whole Foods","cuisine":"Any","K":1050,"P":62,"C":70,"F":50},
    {"name":"Chicken & Pesto Pasta (large) + side Caesar", "chain":"Whole Foods","cuisine":"Any","K":1120,"P":55,"C":110,"F":42},

    {"name":"Mass-gainer smoothie: whole milk, whey double, PB, oats, banana", "chain":"Grocery","cuisine":"Any","K":1000,"P":65,"C":110,"F":30},
    {"name":"Big burrito bowl + tortilla chips & guacamole", "chain":"Grocery","cuisine":"Any","K":1080,"P":48,"C":105,"F":42},
    {"name":"Chicken Alfredo (microwave tray, ~16 oz)", "chain":"Grocery","cuisine":"Any","K":980,"P":50,"C":72,"F":50},

    {"name":"Fairlife 42g shakes (2) + trail mix (1.5 oz)", "chain":"Gas Station","cuisine":"Any","K":980,"P":84,"C":60,"F":36},

    {"name":"Protein Pancakes stack + eggs + turkey bacon", "chain":"IHOP","cuisine":"American","K":1050,"P":55,"C":120,"F":34},
    {"name":"Fit Slam + French toast (single slice)", "chain":"Denny's","cuisine":"American","K":1010,"P":48,"C":120,"F":28},
    # ---- EXTRA MENU ITEMS (broad calorie coverage) ----
{"name":"Harvest Bowl (chicken, no cheese)", "chain":"Sweetgreen","cuisine":"American","K":578,"P":40,"C":55,"F":22},
{"name":"Guacamole Greens (double chicken)", "chain":"Sweetgreen","cuisine":"American","K":596,"P":52,"C":34,"F":28},
{"name":"Kale Caesar (chicken, light parm)", "chain":"Sweetgreen","cuisine":"American","K":456,"P":38,"C":22,"F":24},
{"name":"Fish Taco Bowl (salmon)", "chain":"Sweetgreen","cuisine":"American","K":579,"P":42,"C":42,"F":27},

{"name":"Greens+Grains Bowl (chicken, hummus, harissa)", "chain":"CAVA","cuisine":"Mediterranean","K":694,"P":45,"C":70,"F":26},
{"name":"Greens+Grains Bowl (steak, tzatziki)", "chain":"CAVA","cuisine":"Mediterranean","K":668,"P":48,"C":58,"F":28},
{"name":"Pita (chicken + hummus + veg)", "chain":"CAVA","cuisine":"Mediterranean","K":642,"P":38,"C":72,"F":18},
{"name":"Protein Bowl (double chicken, no pita)", "chain":"CAVA","cuisine":"Mediterranean","K":636,"P":60,"C":26,"F":24},

{"name":"Burrito Bowl: chicken, brown rice, black beans, pico, lettuce", "chain":"Chipotle","cuisine":"Mexican","K":561,"P":46,"C":60,"F":13},
{"name":"Burrito Bowl: steak, white rice, pinto beans, fajita veg, salsa", "chain":"Chipotle","cuisine":"Mexican","K":595,"P":42,"C":64,"F":17},
{"name":"Lifestyle Protein Bowl: double chicken, fajita veg, salsa (no rice/beans)", "chain":"Chipotle","cuisine":"Mexican","K":554,"P":62,"C":18,"F":20},
{"name":"Carnitas Burrito (no queso)", "chain":"Chipotle","cuisine":"Mexican","K":724,"P":40,"C":92,"F":28},

{"name":"Power Menu Bowl (Chicken, no guac)", "chain":"Taco Bell","cuisine":"Mexican","K":449,"P":29,"C":46,"F":12},
{"name":"Power Menu Bowl (Steak, add black beans)", "chain":"Taco Bell","cuisine":"Mexican","K":536,"P":33,"C":58,"F":16},
{"name":"2x Soft Taco (chicken) + Black Beans", "chain":"Taco Bell","cuisine":"Mexican","K":500,"P":36,"C":64,"F":15},

{"name":"Bowl: Grilled Teriyaki Chicken + Super Greens", "chain":"Panda Express","cuisine":"Chinese","K":470,"P":36,"C":26,"F":18},
{"name":"Bowl: String Bean Chicken + Super Greens", "chain":"Panda Express","cuisine":"Chinese","K":356,"P":28,"C":20,"F":12},
{"name":"Plate: Mushroom Chicken + Grilled Teriyaki + Super Greens", "chain":"Panda Express","cuisine":"Chinese","K":662,"P":50,"C":40,"F":28},

{"name":"Greek Chicken Caesar (full) + no croutons", "chain":"Panera","cuisine":"American","K":512,"P":45,"C":20,"F":24},
{"name":"You Pick Two: half Fuji Apple Chicken + Turkey Chili (cup)", "chain":"Panera","cuisine":"American","K":544,"P":40,"C":52,"F":16},
{"name":"Mediterranean Bowl (chicken)", "chain":"Panera","cuisine":"American","K":584,"P":36,"C":60,"F":20},

{"name":"2x Egg McMuffin", "chain":"McDonald's","cuisine":"American","K":500,"P":32,"C":60,"F":18},
{"name":"Quarter Pounder (no cheese) + Side Salad (light balsamic)", "chain":"McDonald's","cuisine":"American","K":510,"P":30,"C":38,"F":22},
{"name":"McCrispy (regular) + Apple Slices", "chain":"McDonald's","cuisine":"American","K":477,"P":29,"C":44,"F":16},

{"name":"Grilled Chicken Sandwich + Small Chili", "chain":"Wendy's","cuisine":"American","K":612,"P":52,"C":68,"F":16},
{"name":"Large Chili + Plain Baked Potato", "chain":"Wendy's","cuisine":"American","K":475,"P":28,"C":92,"F":7},
{"name":"Apple Pecan Chicken Salad (full, light dressing)", "chain":"Wendy's","cuisine":"American","K":484,"P":37,"C":31,"F":20},

{"name":"KFC Grilled Chicken breast + Corn + Green Beans", "chain":"KFC","cuisine":"American","K":461,"P":50,"C":45,"F":9},
{"name":"KFC 3pc Original + Green Beans (no biscuit)", "chain":"KFC","cuisine":"American","K":529,"P":44,"C":22,"F":33},
{"name":"Popeyes Blackened Chicken Tenders (5) + Red Beans & Rice", "chain":"Popeyes","cuisine":"American","K":610,"P":45,"C":54,"F":20},

{"name":"Egg White & Red Pepper Egg Bites + Plain Oatmeal", "chain":"Starbucks","cuisine":"Cafe","K":377,"P":25,"C":44,"F":9},
{"name":"Turkey Bacon, Cheddar & Egg White Sandwich + Oatmeal", "chain":"Starbucks","cuisine":"Cafe","K":610,"P":31,"C":74,"F":14},
{"name":"Spinach, Feta & Egg White Wrap", "chain":"Starbucks","cuisine":"Cafe","K":286,"P":20,"C":34,"F":10},
{"name":"Starbucks Protein Box: Eggs & Cheddar", "chain":"Starbucks","cuisine":"Cafe","K":385,"P":23,"C":37,"F":13},

{"name":"Power Breakfast Sandwich", "chain":"Dunkin'","cuisine":"Cafe","K":392,"P":24,"C":37,"F":14},
{"name":"Turkey Sausage Wake-Up Wrap (2)", "chain":"Dunkin'","cuisine":"Cafe","K":356,"P":24,"C":28,"F":20},

{"name":"#7 Turkey & Provolone (Regular) Mike's Way, no oil", "chain":"Jersey Mike's","cuisine":"Sandwiches","K":546,"P":42,"C":56,"F":18},
{"name":"Turkey & Provolone Bowl (no bread, add extra turkey)", "chain":"Jersey Mike's","cuisine":"Sandwiches","K":548,"P":55,"C":14,"F":24},
{"name":"#13 Original Italian (Mini)", "chain":"Jersey Mike's","cuisine":"Sandwiches","K":422,"P":22,"C":42,"F":16},

{"name":"Turkey Tom (no mayo) + extra turkey", "chain":"Jimmy John's","cuisine":"Sandwiches","K":472,"P":40,"C":48,"F":10},
{"name":"Unwich: Big John (roast beef) + Cheese", "chain":"Jimmy John's","cuisine":"Sandwiches","K":386,"P":32,"C":6,"F":18},

{"name":"No Bready Bowl: Rotisserie-Style Chicken + Veg", "chain":"Subway","cuisine":"Sandwiches","K":364,"P":40,"C":18,"F":12},
{"name":"6\" Turkey on Wheat, double meat, loaded veg, no cheese", "chain":"Subway","cuisine":"Sandwiches","K":420,"P":34,"C":54,"F":8},

{"name":"Zoodles & Grilled Chicken (Pesto, light)", "chain":"Noodles & Company","cuisine":"American","K":430,"P":36,"C":22,"F":22},
{"name":"Small Penne Rosa + Grilled Chicken", "chain":"Noodles & Company","cuisine":"American","K":526,"P":30,"C":58,"F":18},

{"name":"Blaze 11\" Build Your Own: Classic dough, chicken, veg, light mozz", "chain":"Blaze Pizza","cuisine":"Pizza","K":796,"P":40,"C":96,"F":20},
{"name":"MOD Pizza Mini: Chicken, Veg, Light Cheese", "chain":"MOD Pizza","cuisine":"Pizza","K":546,"P":26,"C":62,"F":16},
{"name":"MOD Pizza 11\" Caspian (light cheese) + add chicken", "chain":"MOD Pizza","cuisine":"Pizza","K":820,"P":44,"C":96,"F":28},

{"name":"Single ShackBurger + Side Salad", "chain":"Shake Shack","cuisine":"American","K":701,"P":33,"C":48,"F":40},
{"name":"Little Hamburger + share small fries (half)", "chain":"Five Guys","cuisine":"American","K":635,"P":35,"C":58,"F":40},
{"name":"Five Guys Cheeseburger + share little fries (half)", "chain":"Five Guys","cuisine":"American","K":1163,"P":45,"C":85,"F":72},

{"name":"Create Your Own: spring mix, grilled chicken, apples, cucumbers, balsamic", "chain":"Sweetgreen","cuisine":"American","K":382,"P":34,"C":26,"F":14},

{"name":"Pret Chicken Avocado Salad + Greek Yogurt", "chain":"Pret a Manger","cuisine":"Cafe","K":566,"P":38,"C":36,"F":24},
{"name":"Whole Foods Hot Bar: 8oz grilled salmon + brown rice cup + broccoli", "chain":"Whole Foods","cuisine":"Any","K":686,"P":50,"C":60,"F":24},

{"name":"Smoothie King: Gladiator (Chocolate) 20oz + Peanut Butter add-in", "chain":"Smoothie King","cuisine":"Cafe","K":388,"P":45,"C":10,"F":12},
{"name":"Jamba: Protein Berry Workout (whey) 16oz", "chain":"Jamba","cuisine":"Cafe","K":350,"P":25,"C":58,"F":2},

{"name":"Greek Yogurt (2 cups) + 1/2 cup granola + 1 tbsp honey", "chain":"Grocery","cuisine":"Any","K":612,"P":40,"C":80,"F":12},
{"name":"Cottage cheese (2 cups) + berries + mixed nuts (1 oz)", "chain":"Grocery","cuisine":"Any","K":533,"P":45,"C":40,"F":18},
{"name":"Rotisserie chicken (10 oz) + microwave potato", "chain":"Grocery","cuisine":"Any","K":668,"P":75,"C":50,"F":18},
{"name":"2 cans tuna + avocado + 2 whole-wheat wraps", "chain":"Grocery","cuisine":"Any","K":646,"P":55,"C":50,"F":22},
{"name":"Protein oatmeal: oats + whey + peanut butter", "chain":"Grocery","cuisine":"Any","K":556,"P":40,"C":55,"F":16},
{"name":"High-protein frozen burrito", "chain":"Grocery","cuisine":"Any","K":473,"P":33,"C":50,"F":12},
{"name":"Sushi: 2x spicy tuna rolls", "chain":"Grocery","cuisine":"Any","K":634,"P":34,"C":80,"F":18},
{"name":"Mass-gainer smoothie: whole milk, whey double, PB, oats, banana", "chain":"Grocery","cuisine":"Any","K":1000,"P":65,"C":110,"F":30},

# Add-ons / snacks to fix under-shoot days
{"name":"Fairlife 42g Protein Shake", "chain":"Add-on","cuisine":"Any","K":218,"P":42,"C":8,"F":2},
{"name":"Pure Protein Bar", "chain":"Add-on","cuisine":"Any","K":219,"P":20,"C":18,"F":7},
{"name":"Protein Chips (Quest), 1 bag", "chain":"Add-on","cuisine":"Any","K":141,"P":18,"C":5,"F":4},
{"name":"Apple + 2 tbsp peanut butter", "chain":"Add-on","cuisine":"Any","K":276,"P":8,"C":28,"F":16},
{"name":"Banana + 1 oz almonds", "chain":"Add-on","cuisine":"Any","K":246,"P":6,"C":27,"F":14},
{"name":"String cheese (2) + 1 oz turkey jerky", "chain":"Add-on","cuisine":"Any","K":206,"P":22,"C":4,"F":10},
{"name":"Chobani Nonfat Greek Yogurt (170g) + honey", "chain":"Add-on","cuisine":"Any","K":136,"P":17,"C":17,"F":0},
{"name":"RX Bar", "chain":"Add-on","cuisine":"Any","K":241,"P":12,"C":24,"F":9},
{"name":"Side salad, light vinaigrette", "chain":"Add-on","cuisine":"Any","K":75,"P":2,"C":8,"F":3},
{"name":"Fruit cup", "chain":"Add-on","cuisine":"Any","K":64,"P":1,"C":15,"F":0},
{"name":"Broccoli cup (steamed)", "chain":"Add-on","cuisine":"Any","K":44,"P":3,"C":8,"F":0},

# Higher-calorie choices (kept to retain range for gain/long days)
{"name":"Chipotle Double Chicken Burrito + rice, beans, queso, guac", "chain":"Chipotle","cuisine":"Mexican","K":1150,"P":72,"C":108,"F":42},
{"name":"Panda Bigger Plate: Orange Chicken + Beijing Beef + Chow Mein", "chain":"Panda Express","cuisine":"Chinese","K":1420,"P":45,"C":150,"F":60},
{"name":"McDonald's Double Quarter Pounder w/ Cheese + medium fries", "chain":"McDonald's","cuisine":"American","K":1290,"P":63,"C":103,"F":62},




]

EXTERNAL_MENU = load_menu()  # pulls data/menu.json or MENU_CSV_URL (if set)
MENU: List[Dict[str, Any]] = merged_menu(SEED_MENU, EXTERNAL_MENU)

# -----------------------------
# Energy, macros, and helpers
# -----------------------------
def mifflin_st_jeor(sex: str, weight_kg: float, height_cm: float, age: int) -> float:
    s = 5 if sex and sex.lower().startswith("m") else -161
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + s

def activity_multiplier(level: str) -> float:
    return {
        "sedentary": 1.2, "light": 1.375, "moderate": 1.55, "very": 1.725, "athlete": 1.9,
    }.get((level or "").lower(), 1.55)

def lb_to_kg(lb: float) -> float: return lb * 0.45359237
def in_to_cm(i: float) -> float: return i * 2.54

def calc_tdee_from_stats(sex: str, weight_lb: float, height_in: float, age: int, activity: str) -> int:
    bmr = mifflin_st_jeor(sex, lb_to_kg(weight_lb), in_to_cm(height_in), age)
    return int(round(bmr * activity_multiplier(activity)))

def calorie_goal_from_tdee(tdee: int, goal: str) -> int:
    goal = (goal or "loss25").lower()
    if goal == "loss25": return int(round(tdee * 0.75))
    if goal == "maintain": return int(round(tdee))
    if goal == "gain10": return int(round(tdee * 1.10))
    return int(round(tdee * 0.75))

# ---------------
# Plan generator
# ---------------
@dataclass
class PlanDay:
    items: List[Dict[str, Any]]
    K: int; P: int; C: int; F: int

DEFAULT_MEALS_PER_DAY = 4

def score_combo(picks: List[Dict[str, Any]], cal_target: int, p_target: int, c_target: int, f_target: int) -> Tuple[float, Dict[str, float]]:
    K = sum(x["K"] for x in picks); P = sum(x["P"] for x in picks); C = sum(x["C"] for x in picks); F = sum(x["F"] for x in picks)
    cal_pen = abs(K - cal_target) / 6.0
    prot_short = max(0, p_target - P); prot_pen = prot_short * 8.5
    fat_overshoot = max(0, F - f_target * 1.25); carb_overshoot = max(0, C - c_target * 1.35)
    macro_pen = (fat_overshoot * 0.7) + (carb_overshoot * 0.3)
    chains = {x["chain"] for x in picks}; variety_bonus = -0.4 * (len(chains) - 1)
    score = cal_pen + prot_pen + macro_pen + variety_bonus
    meta = {"K": K, "P": P, "C": C, "F": F}
    return score, meta

def macro_targets(calories: int, protein_g: Optional[int] = None) -> Tuple[int, int, int]:
    if protein_g is None:
        protein_g = int(round(0.35 * calories / 4))
    remaining_cal = calories - protein_g * 4
    carbs_g = int(round((remaining_cal * 0.5) / 4))
    fat_g = int(round((remaining_cal * 0.5) / 9))
    return protein_g, carbs_g, fat_g

def pick_combo(pool: List[Dict[str, Any]], cal_target: int, meals_per_day: int, p_target: int, c_target: int, f_target: int) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    ideal = cal_target / max(1, meals_per_day)
    top_pool = sorted(pool, key=lambda x: abs(x["K"] - ideal))[:max(10, int(len(pool)*0.8))]
    best_score = float("inf"); best_combo=None; best_meta=None
    TRIES = min(5000, max(1500, len(top_pool) * 250))
    for _ in range(TRIES):
        k = min(meals_per_day, len(top_pool)); picks = random.sample(top_pool, k=k)
        s, meta = score_combo(picks, cal_target, p_target, c_target, f_target)
        if s < best_score: best_score, best_combo, best_meta = s, picks, meta
    if best_meta and abs(best_meta.get("K", 0) - cal_target) > 125:
        for _ in range(1500):
            picks = random.sample(top_pool, k=min(meals_per_day, len(top_pool)))
            s, meta = score_combo(picks, cal_target, p_target, c_target, f_target)
            if s < best_score:
                best_score, best_combo, best_meta = s, picks, meta
                if abs(best_meta["K"] - cal_target) <= 125: break
    return best_combo or [], best_meta or {"K":0,"P":0,"C":0,"F":0}

def filter_menu(menu: List[Dict[str, Any]], cuisine: Optional[str], chain: Optional[str]) -> List[Dict[str, Any]]:
    out = menu
    if cuisine: out = [m for m in out if m["cuisine"].lower().startswith(cuisine.lower())]
    if chain: out = [m for m in out if m["chain"].lower() == chain.lower()]
    return out if out else menu

def generate_plan(calories: int, cuisine: Optional[str], chain: Optional[str], days: int = 3,
                  protein_g_override: Optional[int] = None, meals_per_day: int = DEFAULT_MEALS_PER_DAY) -> Dict[str, Any]:
    menu = filter_menu(MENU, cuisine, chain)
    p_target, c_target, f_target = macro_targets(calories, protein_g_override)
    plan_days: List[PlanDay] = []
    for _ in range(days):
        picks, meta = pick_combo(menu, calories, meals_per_day, p_target, c_target, f_target)
        plan_days.append(PlanDay(items=picks, K=int(meta["K"]), P=int(meta["P"]), C=int(meta["C"]), F=int(meta["F"])))
    return {
        "days": days, "cuisine": cuisine, "chain": chain,
        "meals_per_day": meals_per_day,
        "protein_target": p_target, "carb_target": c_target, "fat_target": f_target,
        "plan": [{"items": d.items, "K": d.K, "P": d.P, "C": d.C, "F": d.F} for d in plan_days]
    }

# -----------------------------
# Standalone HTML templates
# -----------------------------
INDEX_HTML = r"""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>
:root { --bg:#0b0e11; --card:#131820; --ink:#e8eef6; --muted:#9bb0c3; --accent:#68b5ff; }
*{box-sizing:border-box} body{margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
 background:var(--bg); color:var(--ink);}
a{color:var(--accent); text-decoration:none} a.underline{text-decoration:underline}
.container{max-width:980px; margin:24px auto; padding:0 16px}
.header{display:flex; justify-content:space-between; align-items:center; margin-bottom:18px}
.brand{font-weight:700; font-size:20px}
.card{background:var(--card); border:1px solid #1e2835; border-radius:16px; padding:16px; margin:10px 0; box-shadow: 0 8px 24px rgba(0,0,0,.25)}
.grid{display:grid; gap:12px} .g2{grid-template-columns:1fr 1fr} .g3{grid-template-columns:1fr 1fr 1fr}
label{display:block; font-size:12px; color:var(--muted); margin-bottom:6px}
input,select{width:100%; padding:10px 12px; border-radius:10px; background:#0f141b; border:1px solid #253142; color:#e8eef6}
button{padding:10px 14px; border-radius:12px; background:var(--accent); color:#021627; border:0; font-weight:700; cursor:pointer}
.kbd{background:#0f141b; border:1px solid #253142; padding:1px 6px; border-radius:6px}
.muted{color:var(--muted)} .small{font-size:12px}
</style>
<div class="container">
  <div class="header">
    <div class="brand">Concierge Meal Generator</div>
    <div class="muted small">Travel-friendly · Protein-first · Smart deficit</div>
  </div>
  <div class="card">
    <form action="{{ url_for('plan') }}" method="get" class="grid g3">
      <div>
        <label>TDEE (if known)</label>
        <input type="number" name="tdee" placeholder="e.g., 2400" value="{{ req.get('tdee','') }}" min="1000" max="6000">
        <div class="muted small" style="margin-top:4px;">We'll apply goal below (default: -25%).</div>
      </div>
      <div>
        <label>Goal</label>
        <select name="goal">
          <option value="loss25" {% if req.get('goal','loss25')=='loss25' %}selected{% endif %}>Weight loss (-25%)</option>
          <option value="maintain" {% if req.get('goal')=='maintain' %}selected{% endif %}>Maintain</option>
          <option value="gain10" {% if req.get('goal')=='gain10' %}selected{% endif %}>Gain (+10%)</option>
        </select>
      </div>
      <div>
        <label>Days</label>
        <input type="number" name="days" value="{{ req.get('days',3) }}" min="1" max="7">
      </div>

      <div>
        <label>Meals per day</label>
        <select name="meals_per_day">
          <option value="2" {% if req.get('meals_per_day','4')=='2' %}selected{% endif %}>2</option>
          <option value="3" {% if req.get('meals_per_day','4')=='3' %}selected{% endif %}>3</option>
          <option value="4" {% if req.get('meals_per_day','4')=='4' %}selected{% endif %}>4</option>
        </select>
      </div>

      <div style="grid-column:1/-1;">
        <label>Don’t know your TDEE? Estimate from stats</label>
        <div class="grid g3">
          <select name="sex">
            <option value="">Sex</option>
            <option value="male"   {% if req.get('sex')=='male' %}selected{% endif %}>Male</option>
            <option value="female" {% if req.get('sex')=='female' %}selected{% endif %}>Female</option>
          </select>
          <input name="age" type="number" placeholder="Age" value="{{ req.get('age','') }}">
          <select name="activity">
            <option value="sedentary" {% if req.get('activity')=='sedentary' %}selected{% endif %}>Sedentary</option>
            <option value="light"     {% if req.get('activity')=='light' %}selected{% endif %}>Light</option>
            <option value="moderate"  {% if req.get('activity','moderate')=='moderate' %}selected{% endif %}>Moderate</option>
            <option value="very"      {% if req.get('activity')=='very' %}selected{% endif %}>Very</option>
            <option value="athlete"   {% if req.get('activity')=='athlete' %}selected{% endif %}>Athlete</option>
          </select>
        </div>
        <div class="grid g3" style="margin-top:8px;">
          <input name="weight_lb" type="number" step="0.1" min="60" max="600" placeholder="Weight (lb)" required value="{{ req.get('weight_lb','') }}">
          <input name="height_in" type="number" step="0.1" placeholder="Height (in)" value="{{ req.get('height_in','') }}">
          <div class="muted small" style="align-self:center;">Protein target uses 1.0 g/lb. We'll estimate calories if TDEE is blank.</div>
        </div>
      </div>

      <div>
        <label>Chain (optional)</label>
        <input name="chain" placeholder="e.g., Chipotle" value="{{ req.get('chain','') }}">
      </div>
      <div>
        <label>Cuisine (optional)</label>
        <input name="cuisine" placeholder="e.g., Mexican" value="{{ req.get('cuisine','') }}">
      </div>
      <div style="display:flex; align-items:end; gap:8px;">
        <button type="submit">Generate Plan</button>
        <a href="{{ url_for('seed_sample_route') }}" class="underline muted small" title="View sample items">View sample items</a>
      </div>
    </form>
  </div>
</div>
"""

PLAN_HTML = r"""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>
:root { --bg:#0b0e11; --card:#131820; --ink:#e8eef6; --muted:#9bb0c3; --accent:#68b5ff; }
*{box-sizing:border-box} body{margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
 background:var(--bg); color:var(--ink);}
a{color:var(--accent); text-decoration:none} a.underline{text-decoration:underline}
.container{max-width:980px; margin:24px auto; padding:0 16px}
.header{display:flex; justify-content:space-between; align-items:center; margin-bottom:18px}
.brand{font-weight:700; font-size:20px}
.card{background:var(--card); border:1px solid #1e2835; border-radius:16px; padding:16px; margin:10px 0; box-shadow: 0 8px 24px rgba(0,0,0,.25)}
.grid{display:grid; gap:12px} .g2{grid-template-columns:1fr 1fr} .g3{grid-template-columns:1fr 1fr 1fr}
label{display:block; font-size:12px; color:var(--muted); margin-bottom:6px}
input,select{width:100%; padding:10px 12px; border-radius:10px; background:#0f141b; border:1px solid #253142; color:#e8eef6}
button{padding:10px 14px; border-radius:12px; background:var(--accent); color:#021627; border:0; font-weight:700; cursor:pointer}
.kbd{background:#0f141b; border:1px solid #253142; padding:1px 6px; border-radius:6px}
.muted{color:var(--muted)} .small{font-size:12px}
.meal{padding:10px 0; border-top:1px dashed #2a3647} .meal:first-child{border-top:0}
.bul{margin:0; padding-left:18px}
</style>
<div class="container">
  <div class="header">
    <div class="brand">Concierge Meal Generator</div>
    <div class="muted small">Travel-friendly · Protein-first · Smart deficit</div>
  </div>
  <div class="card">
    <div style="display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap;">
      <div><strong>{{ calories }} kcal/day</strong> · Protein target {{ data.protein_target }}g · Carbs {{ data.carb_target }}g · Fat {{ data.fat_target }}g</div>
      <div class="muted">{{ data.cuisine or data.chain or 'All menus' }} · {{ data.days }} days · {{ data.meals_per_day }} meals/day</div>
    </div>
    {% if data._meta and data._meta.note %}
      <div class="muted small" style="margin-top:6px;">{{ data._meta.note }}</div>
    {% endif %}
    <div style="margin-top:10px;">
      <a class="underline" href="{{ url_for('export_pdf') }}?{{ request.query_string.decode('utf-8') }}">Download PDF</a>
    </div>
  </div>
  {% for d in data.plan %}
    <div class="card">
      <div><strong>Day {{ loop.index }}</strong> &nbsp; <span class="muted small">Totals: {{ d.K }} kcal · {{ d.P }}g P · {{ d.C }}g C · {{ d.F }}g F</span></div>
      <div>
        {% for it in d["items"] %}
          <div class="meal">
            <div><strong>{{ it.name }}</strong></div>
            <div class="muted small">{{ it.chain }} · {{ it.cuisine }}</div>
            <ul class="bul small">
              <li>{{ it.K }} kcal</li>
              <li>{{ it.P }}g protein · {{ it.C }}g carbs · {{ it.F }}g fat</li>
            </ul>
          </div>
        {% endfor %}
      </div>
    </div>
  {% endfor %}
  <div class="card small muted">Generated {{ now }}</div>
</div>
"""

SEED_HTML = r"""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>
:root { --bg:#0b0e11; --card:#131820; --ink:#e8eef6; --muted:#9bb0c3; --accent:#68b5ff; }
*{box-sizing:border-box} body{margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
 background:var(--bg); color:var(--ink);}
a{color:var(--accent); text-decoration:none} a.underline{text-decoration:underline}
.container{max-width:980px; margin:24px auto; padding:0 16px}
.header{display:flex; justify-content:space-between; align-items:center; margin-bottom:18px}
.brand{font-weight:700; font-size:20px}
.card{background:var(--card); border:1px solid #1e2835; border-radius:16px; padding:16px; margin:10px 0; box-shadow: 0 8px 24px rgba(0,0,0,.25)}
.small{font-size:12px} .bul{margin:0; padding-left:18px}
</style>
<div class="container">
  <div class="header">
    <div class="brand">Concierge Meal Generator</div>
    <div class="muted small">Travel-friendly · Protein-first · Smart deficit</div>
  </div>
  <div class="card">
    <h3>Sample Items</h3>
    <ul class="bul">
      {% for it in items %}<li class="small">{{ it }}</li>{% endfor %}
    </ul>
    <div class="muted small">Add more items by editing MENU in concierge_app.py</div>
    <a class="underline" href="{{ url_for('index') }}">Back</a>
  </div>
</div>
"""

# -----------------------------
# PDF builder
# -----------------------------
def write_pdf_plan(path: str, plan: Dict[str, Any], calories: int):
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab is required for PDF export. Install with: pip install reportlab")
    doc = SimpleDocTemplate(path, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=40, bottomMargin=36)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1", parent=styles["Heading1"], fontSize=20, leading=24, textColor=colors.HexColor("#0b0e11")))
    styles.add(ParagraphStyle(name="H2", parent=styles["Heading2"], fontSize=14, leading=18, textColor=colors.HexColor("#0b0e11")))
    styles.add(ParagraphStyle(name="Meta", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#45566b")))
    styles.add(ParagraphStyle(name="Cell", parent=styles["Normal"], fontSize=10, leading=13))
    styles.add(ParagraphStyle(name="Kicker", parent=styles["Normal"], fontSize=11, textColor=colors.HexColor("#021627")))
    story = []
    title = f"{APP_NAME} — {datetime.datetime.now().strftime('%Y-%m-%d')}"
    kicker = f"Target: {calories} kcal/day • Protein {plan['protein_target']}g • Carbs {plan['carb_target']}g • Fat {plan['fat_target']}g"
    meta = f"Filters: cuisine={plan['cuisine'] or 'Any'} • chain={plan['chain'] or 'Any'}"
    header_tbl = Table([[Paragraph(title, styles["H1"])]],[6.5*inch])
    header_tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#68b5ff")),("LEFTPADDING",(0,0),(-1,-1),12),
                                    ("RIGHTPADDING",(0,0),(-1,-1),12),("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
                                    ("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    story += [header_tbl, Spacer(1, 6), Paragraph(kicker, styles["Kicker"]), Paragraph(meta, styles["Meta"]), Spacer(1, 12)]
    for idx, d in enumerate(plan["plan"], start=1):
        story.append(Paragraph(f"Day {idx}", styles["H2"]))
        story.append(Paragraph(f"Totals: {d['K']} kcal • {d['P']}g P • {d['C']}g C • {d['F']}g F", styles["Meta"]))
        story.append(Spacer(1, 6))
        data_rows = [["Meal", "Chain / Cuisine", "kcal", "P", "C", "F"]]
        for it in d["items"]:
            data_rows.append([Paragraph(it["name"], styles["Cell"]), Paragraph(f"{it['chain']} • {it['cuisine']}", styles["Cell"]),
                              str(it["K"]), str(it["P"]), str(it["C"]), str(it["F"])])
        tbl = Table(data_rows, colWidths=[3.1*inch, 1.8*inch, 0.6*inch, 0.4*inch, 0.4*inch, 0.4*inch])
        tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#131820")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
                                 ("LINEBELOW",(0,0),(-1,0),1,colors.HexColor("#0b0e11")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
                                 ("ALIGN",(2,1),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"TOP"),
                                 ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#f2f6fb"), colors.white]),
                                 ("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#d5e2f3")),
                                 ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
                                 ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
        story += [tbl, Spacer(1, 12)]
        if idx % 3 == 0 and idx != len(plan["plan"]): story.append(PageBreak())
    story.append(Spacer(1, 12)); story.append(Paragraph(f"Generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Meta"]))
    doc.build(story)

# -----------------------------
# Helpers
# -----------------------------
def _resolve_from_request(req):
    calories_param = req.get("calories"); tdee = req.get("tdee"); goal = req.get("goal", "loss25")
    sex = req.get("sex"); weight_lb = req.get("weight_lb"); height_in = req.get("height_in"); age = req.get("age")
    activity = req.get("activity", "moderate")
    cuisine = req.get("cuisine") or None; chain = req.get("chain") or None; days = int(req.get("days", 3))

    # Meals per day from UI (allow 2,3,4)
    try:
        meals_per_day = int(req.get("meals_per_day", DEFAULT_MEALS_PER_DAY))
    except Exception:
        meals_per_day = DEFAULT_MEALS_PER_DAY
    if meals_per_day not in (2,3,4):
        meals_per_day = DEFAULT_MEALS_PER_DAY

    meta_note = None
    try:
        if calories_param:
            calories_resolved = int(calories_param); meta_note = f"Using explicit calories = {calories_resolved}"
        else:
            if tdee: tdee = int(tdee)
            else:
                if all([sex, weight_lb, height_in, age]):
                    tdee = calc_tdee_from_stats(sex=sex, weight_lb=float(weight_lb), height_in=float(height_in), age=int(age), activity=activity)
                else:
                    tdee = 2000; meta_note = "Fallback: TDEE defaulted to 2000"
            calories_resolved = calorie_goal_from_tdee(int(tdee), goal)
            if not meta_note: meta_note = f"TDEE {tdee} → goal '{goal}' ⇒ {calories_resolved} kcal/day"
    except Exception:
        calories_resolved = 2000; meta_note = "Invalid inputs; defaulted to 2000 kcal"

    # Fixed 1.0 g/lb protein target
    try:
        bw = float(weight_lb) if weight_lb else None
        protein_g = int(round(bw)) if bw else None
    except Exception:
        protein_g = None

    data = generate_plan(calories_resolved, cuisine, chain, days, protein_g, meals_per_day)
    data["_meta"] = {"note": meta_note}
    return data, calories_resolved

# -----------------------------
# Routes
# -----------------------------
@app.route("/")
def index():
    return render_template_string(INDEX_HTML, title=f"{APP_NAME} — Home", req=request.args)

@app.route("/plan")
def plan():
    data, calories_resolved = _resolve_from_request(request.args)
    return render_template_string(PLAN_HTML, title=f"{APP_NAME} — Plan", data=data, calories=calories_resolved, now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), request=request)

@app.route("/seed")
def seed_sample_route():
    items = [f"{m['chain']} · {m['name']} — {m['K']} kcal / {m['P']}P/{m['C']}C/{m['F']}F" for m in MENU[:30]]
    return render_template_string(SEED_HTML, title=f"{APP_NAME} — Seed", items=items)

@app.route("/export/pdf")
def export_pdf():
    if not REPORTLAB_AVAILABLE:
        html = "<h3>PDF export not available</h3><p>Install ReportLab first: <code>pip install reportlab</code></p>"
        return make_response(html, 501)
    data, calories_resolved = _resolve_from_request(request.args)
    outdir = pathlib.Path("artifacts"); outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = outdir / f"concierge_plan_{stamp}.pdf"
    write_pdf_plan(str(pdf_path), data, calories_resolved)
    return send_from_directory(outdir, pdf_path.name, as_attachment=True, download_name=pdf_path.name)

# -----------------------------
# Headless export
# -----------------------------
def write_html_plan(path: str, plan: Dict[str, Any], calories: int):
    """Headless-friendly HTML writer (no Flask context)."""
    style = """
    <style>
      body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px;color:#0b0e11;}
      .hdr{background:#68b5ff;color:#021627;padding:14px 16px;border-radius:12px;font-weight:700;font-size:18px;}
      .meta{color:#45566b;font-size:12px;margin-top:6px;}
      .day{border:1px solid #d5e2f3;border-radius:12px;padding:12px;margin-top:14px;}
      table{width:100%;border-collapse:collapse;margin-top:8px;}
      th,td{border:1px solid #d5e2f3;padding:8px;font-size:13px;vertical-align:top;}
      th{background:#131820;color:#fff;text-align:left;}
    </style>
    """
    header = f"<div class='hdr'>{APP_NAME} — {datetime.datetime.now().strftime('%Y-%m-%d')}</div>"
    kicker = f"<div class='meta'>Target: {calories} kcal/day • Protein {plan['protein_target']}g • Carbs {plan['carb_target']}g • Fat {plan['fat_target']}g</div>"
    filt = f"<div class='meta'>Filters: cuisine={plan['cuisine'] or 'Any'} • chain={plan['chain'] or 'Any'}</div>"
    parts = [f"<!doctype html><meta charset='utf-8'><title>Plan</title>{style}", header, kicker, filt]
    for i, d in enumerate(plan["plan"], 1):
        parts.append(f"<div class='day'><b>Day {i}</b> <span class='meta'>Totals: {d['K']} kcal • {d['P']}g P • {d['C']}g C • {d['F']}g F</span>")
        rows = ["<table><tr><th>Meal</th><th>Chain / Cuisine</th><th>kcal</th><th>P</th><th>C</th><th>F</th></tr>"]
        for it in d["items"]:
            rows.append(f"<tr><td>{it['name']}</td><td>{it['chain']} • {it['cuisine']}</td><td>{it['K']}</td><td>{it['P']}</td><td>{it['C']}</td><td>{it['F']}</td></tr>")
        rows.append("</table></div>"); parts.append("".join(rows))
    parts.append(f"<div class='meta'>Generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</div>")
    html = "\n".join(parts)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

def headless_export(calories: int, cuisine: Optional[str], chain: Optional[str], days: int, protein_g: Optional[int], meals_per_day: int, out_dir: str) -> Dict[str, str]:
    plan = generate_plan(calories, cuisine, chain, days, protein_g, meals_per_day)
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S"); base = out / f"concierge_plan_{stamp}"
    files = {"json": str(base.with_suffix(".json")), "pdf": str(base.with_suffix(".pdf")), "html": str(base.with_suffix(".html"))}
    with open(files["json"], "w", encoding="utf-8") as f: json.dump(plan, f, indent=2)
    write_html_plan(files["html"], plan, calories)
    if REPORTLAB_AVAILABLE: write_pdf_plan(files["pdf"], plan, calories)
    else:
        with open(str(base.with_suffix(".pdf.MISSING.txt")), "w", encoding="utf-8") as f:
            f.write("Install ReportLab to enable PDF export: pip install reportlab\n")
    return files

# -----------------------------
# CLI
# -----------------------------
def main_cli():
    parser = argparse.ArgumentParser(description="Concierge Meal Generator")
    parser.add_argument("--host", default="0.0.0.0"); parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5000)))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--headless", action="store_true"); parser.add_argument("--out", type=str, default="artifacts")
    parser.add_argument("--calories", type=int, default=None); parser.add_argument("--tdee", type=int, default=None); parser.add_argument("--goal", type=str, default="loss25")
    parser.add_argument("--sex", type=str, default=None); parser.add_argument("--weight_lb", type=float, default=None); parser.add_argument("--height_in", type=float, default=None)
    parser.add_argument("--age", type=int, default=None); parser.add_argument("--activity", type=str, default="moderate")
    parser.add_argument("--cuisine", type=str, default=None); parser.add_argument("--chain", type=str, default=None); parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--meals_per_day", type=int, choices=[2,3,4], default=DEFAULT_MEALS_PER_DAY)
    args = parser.parse_args()

    if not args.headless:
        app.run(host=args.host, port=args.port, debug=args.debug); return

    if args.calories:
        calories_resolved = int(args.calories)
    else:
        if args.tdee:
            tdee = int(args.tdee)
        elif all([args.sex, args.weight_lb, args.height_in, args.age]):
            tdee = calc_tdee_from_stats(args.sex, float(args.weight_lb), float(args.height_in), int(args.age), args.activity)
        else:
            tdee = 2000
        calories_resolved = calorie_goal_from_tdee(tdee, args.goal)

    # Fixed 1.0 g/lb for CLI too
    protein_resolved = int(round(args.weight_lb)) if args.weight_lb else None

    files = headless_export(calories_resolved, args.cuisine, args.chain, args.days, protein_resolved, args.meals_per_day, args.out)
    print("Headless export complete:"); [print(f"  {k}: {v}") for k,v in files.items()]
    if not REPORTLAB_AVAILABLE: print("\nNOTE: PDF not generated (ReportLab missing). Install with: pip install reportlab")

if __name__ == "__main__":
    main_cli()



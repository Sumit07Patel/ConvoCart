"""Query understanding for English, Hindi (Devanagari) and Hinglish shopper messages.

Turns "monsoon ke liye ek halki waterproof jacket dikhao, 3000 ke andar" into
  text  = "monsoon rain waterproof lightweight waterproof jacket"
  filters = {max_price: 3000, categories: ["rain jacket"]}
Rules are small and explicit on purpose so failures are easy to read in the search eval.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Multi-word phrases first (applied on the lowercased string).
PHRASES: dict[str, str] = {
    "t shirt": "tshirt", "t-shirt": "tshirt", "tee shirt": "tshirt", "rain coat": "raincoat",
    "flip flop": "flipflop", "flip flops": "flipflop", "back pack": "backpack", "laptop bag": "laptop backpack",
    "running shoes": "running sneakers", "sports shoes": "running sneakers", "walking shoes": "walking sneakers",
    "water proof": "waterproof", "light weight": "lightweight", "quick dry": "quick-dry",
    "के लिए": " ", "से कम": " lt ", "के अंदर": " lt ", "के नीचे": " lt ", "से ज्यादा": " gt ", "से ऊपर": " gt ",
    "ke andar": " lt ", "ke under": " lt ", "se kam": " lt ", "ke neeche": " lt ", "ke niche": " lt ",
    "se neeche": " lt ", "ke bheetar": " lt ", "se zyada": " gt ", "se jyada": " gt ", "se upar": " gt ",
    "less than": " lt ", "up to": " lt ", "or less": " lt ", "and below": " lt ", "more than": " gt ",
}

# token -> replacement tokens (English concepts the catalog uses)
LEXICON: dict[str, list[str]] = {
    # weather / use
    "monsoon": ["monsoon", "rain", "waterproof"], "barsaat": ["monsoon", "rain", "waterproof"],
    "baarish": ["monsoon", "rain", "waterproof"], "barish": ["monsoon", "rain", "waterproof"],
    "rainy": ["rain", "monsoon", "waterproof"], "rain": ["rain", "monsoon", "waterproof"],
    "बारिश": ["monsoon", "rain", "waterproof"], "मानसून": ["monsoon", "rain", "waterproof"],
    "बरसात": ["monsoon", "rain", "waterproof"],
    "waterproof": ["waterproof"], "वाटरप्रूफ": ["waterproof"],
    "halki": ["lightweight"], "halka": ["lightweight"], "halke": ["lightweight"], "light": ["lightweight"],
    "हल्की": ["lightweight"], "हल्का": ["lightweight"], "हल्के": ["lightweight"],
    "garam": ["warm"], "garm": ["warm"], "गरम": ["warm"], "गर्म": ["warm"],
    "thand": ["winter", "warm"], "thandi": ["winter", "warm"], "sardi": ["winter", "warm"], "sardiyon": ["winter", "warm"],
    "सर्दी": ["winter", "warm"], "सर्दियों": ["winter", "warm"], "ठंड": ["winter", "warm"],
    "garmi": ["summer", "breathable"], "garmiyon": ["summer", "breathable"], "गर्मी": ["summer", "breathable"],
    "गर्मियों": ["summer", "breathable"], "dhoop": ["uv", "summer"], "धूप": ["uv", "summer"],
    "shaadi": ["wedding", "festive"], "shadi": ["wedding", "festive"], "vivah": ["wedding", "festive"],
    "शादी": ["wedding", "festive"], "wedding": ["wedding", "festive"],
    "tyohar": ["festive"], "diwali": ["festive"], "festival": ["festive"], "त्योहार": ["festive"], "दिवाली": ["festive"],
    "daftar": ["office"], "दफ्तर": ["office"], "ऑफिस": ["office"], "naukri": ["office"],
    "pahad": ["trek"], "pahadon": ["trek"], "trekking": ["trek"], "hiking": ["trek"], "पहाड़": ["trek"],
    "safar": ["travel"], "yatra": ["travel"], "सफर": ["travel"], "यात्रा": ["travel"],
    "daud": ["running"], "दौड़": ["running"], "gym": ["sports"],
    "bike": ["commute"], "commute": ["commute"],
    # products
    "jacket": ["jacket"], "jaket": ["jacket"], "जैकेट": ["jacket"], "raincoat": ["raincoat", "rain", "waterproof"],
    "रेनकोट": ["raincoat", "rain", "waterproof"], "windcheater": ["windcheater", "jacket"],
    "kurta": ["kurta"], "कुर्ता": ["kurta"], "kurte": ["kurta"], "kurti": ["kurti"], "कुर्ती": ["kurti"],
    "tshirt": ["tshirt"], "tee": ["tshirt"], "टीशर्ट": ["tshirt"], "टी-शर्ट": ["tshirt"],
    "shirt": ["shirt"], "kameez": ["shirt"], "शर्ट": ["shirt"], "कमीज़": ["shirt"],
    "jeans": ["jeans"], "जींस": ["jeans"], "pant": ["trousers"], "pants": ["trousers"], "trouser": ["trousers"],
    "trousers": ["trousers"], "chinos": ["trousers", "chinos"], "पैंट": ["trousers"], "patloon": ["trousers"],
    "shoes": ["shoes"], "shoe": ["shoes"], "joote": ["shoes"], "joota": ["shoes"], "jute": ["shoes"],
    "जूते": ["shoes"], "जूता": ["shoes"], "sneakers": ["sneakers", "shoes"], "sneaker": ["sneakers", "shoes"],
    "sandals": ["sandals"], "sandal": ["sandals"], "chappal": ["sandals"], "chappals": ["sandals"],
    "चप्पल": ["sandals"], "floaters": ["floaters", "sandals"], "slippers": ["sandals"], "flipflop": ["sandals", "flip"],
    "juttis": ["juttis", "sandals"], "jutti": ["juttis", "sandals"],
    "bag": ["bag"], "bags": ["bag"], "backpack": ["backpack", "bag"], "बैग": ["bag"], "basta": ["bag"],
    "rucksack": ["rucksack", "backpack", "bag"], "duffel": ["duffel", "bag"],
    "umbrella": ["umbrella"], "chhata": ["umbrella"], "chata": ["umbrella"], "chhatri": ["umbrella"], "छाता": ["umbrella"],
    "watch": ["watch"], "ghadi": ["watch"], "घड़ी": ["watch"],
    "socks": ["socks"], "moze": ["socks"], "moje": ["socks"], "मोज़े": ["socks"], "मोजे": ["socks"],
    "cap": ["cap"], "topi": ["cap"], "टोपी": ["cap"], "hat": ["cap", "hat"], "beanie": ["cap", "beanie"],
    "dupatta": ["dupatta"], "दुपट्टा": ["dupatta"], "chunni": ["dupatta"],
    "hoodie": ["hoodie"], "sweatshirt": ["hoodie", "sweatshirt"], "हुडी": ["hoodie"],
    "saree": ["saree"], "sari": ["saree"], "साड़ी": ["saree"], "wallet": ["wallet"], "batua": ["wallet"],
    "बटुआ": ["wallet"], "vest": ["vest"],
    # people
    "ladies": ["women"], "mahila": ["women"], "women": ["women"], "womens": ["women"], "girls": ["women"],
    "महिला": ["women"], "biwi": ["women"], "wife": ["women"], "mummy": ["women"], "maa": ["women"],
    "gents": ["men"], "mens": ["men"], "men": ["men"], "papa": ["men"], "husband": ["men"], "pati": ["men"],
    "kids": ["kids"], "bachche": ["kids"], "bachcho": ["kids"], "bacche": ["kids"], "बच्चों": ["kids"], "beta": ["kids"],
}

STOPWORDS = {
    "a", "an", "the", "for", "me", "i", "want", "need", "show", "some", "any", "please", "pls", "with", "and", "or",
    "of", "to", "in", "on", "is", "my", "one", "good", "nice", "best", "looking", "find", "get", "give", "can", "you",
    "ke", "ka", "ki", "ek", "dikhao", "dikha", "dikhana", "chahiye", "mujhe", "mere", "meri", "mera", "liye", "hai",
    "koi", "wala", "wali", "wale", "kuch", "aur", "se", "me", "mein", "bhi", "do", "de", "dena", "batao", "bata",
    "acchi", "achhi", "accha", "achha", "badhiya", "zara", "jo", "ho", "ji", "bhai", "yaar", "kya", "hain",
    "एक", "दिखाओ", "दिखाइए", "मुझे", "चाहिए", "के", "की", "का", "लिए", "है", "कोई", "और", "में", "भी", "दो",
    "rs", "inr", "rupees", "rupaye", "rupay", "₹", "रुपये", "size", "number", "lt", "gt", "under", "below",
    "within", "upto", "max", "budget", "above", "over", "tak", "तक", "between", "price", "around", "range",
    "unisex", "uk",
}

COLORS: dict[str, str] = {
    "black": "black", "kala": "black", "kaala": "black", "kaali": "black", "kali": "black", "kaale": "black", "kale": "black", "काला": "black", "काली": "black",
    "white": "white", "safed": "white", "सफेद": "white", "सफ़ेद": "white",
    "blue": "blue", "neela": "blue", "neeli": "blue", "नीला": "blue", "नीली": "blue",
    "navy": "navy", "red": "red", "laal": "red", "lal": "red", "लाल": "red",
    "green": "green", "hara": "green", "hari": "green", "हरा": "green", "हरी": "green",
    "yellow": "yellow", "peela": "yellow", "peeli": "yellow", "पीला": "yellow", "पीली": "yellow",
    "grey": "grey", "gray": "grey", "brown": "brown", "bhura": "brown", "भूरा": "brown",
    "pink": "pink", "gulabi": "pink", "गुलाबी": "pink", "maroon": "maroon", "olive": "olive", "beige": "beige",
    "mustard": "mustard", "teal": "teal", "tan": "tan", "gold": "gold", "silver": "silver",
}

# concept token -> catalog categories
CATEGORY_OF: dict[str, list[str]] = {
    "raincoat": ["rain jacket"], "windcheater": ["rain jacket"], "kurta": ["kurta"], "kurti": ["kurti"],
    "tshirt": ["t-shirt"], "shirt": ["shirt"], "jeans": ["jeans"], "trousers": ["trousers"],
    "shoes": ["sneakers", "sandals"], "sneakers": ["sneakers"], "sandals": ["sandals"], "bag": ["backpack"],
    "backpack": ["backpack"], "umbrella": ["umbrella"], "watch": ["watch"], "socks": ["socks"], "cap": ["cap"],
    "dupatta": ["dupatta"], "hoodie": ["hoodie"], "saree": ["saree"], "wallet": ["wallet"], "vest": ["winter jacket"],
}

CATEGORIES = ["rain jacket", "winter jacket", "kurta", "kurti", "t-shirt", "shirt", "jeans", "trousers", "sneakers",
              "sandals", "backpack", "umbrella", "watch", "socks", "cap", "hoodie", "saree", "wallet", "dupatta"]

def resolve_category(name: str) -> list[str]:
    """Map a model-supplied category ('jacket', 'Jackets', 'shoes', 'जूते') to catalog categories.
    Returns [] when nothing matches, so the caller drops the filter instead of filtering everything out."""
    name = name.strip().lower()
    if name in CATEGORIES:
        return [name]
    for candidate in (name, re.sub(r"(es|s)$", "", name)):
        cats = parse_query(candidate).categories
        if cats:
            return cats
    return []


SIZE_WORDS = {"xs": "XS", "small": "S", "medium": "M", "large": "L", "xl": "XL", "xxl": "XXL", "2xl": "XXL",
              "s": "S", "m": "M", "l": "L"}


@dataclass
class ParsedQuery:
    raw: str
    text: str
    tokens: list[str]
    max_price: int | None = None
    min_price: int | None = None
    categories: list[str] = field(default_factory=list)
    size: str | None = None
    color: str | None = None
    gender: str | None = None

    def filters(self) -> dict:
        return {k: v for k, v in {"max_price": self.max_price, "min_price": self.min_price,
                                  "categories": self.categories or None, "size": self.size, "color": self.color,
                                  "gender": self.gender}.items() if v}


_NUM = r"(\d[\d,]*(?:\.\d+)?\s*k?)"


def _num(s: str) -> int:
    s = s.replace(",", "").strip().lower()
    mult = 1000 if s.endswith("k") else 1
    return int(float(s.rstrip("k").strip()) * mult)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[\wऀ-ॿ\-]+|₹", text.lower())


def parse_query(raw: str) -> ParsedQuery:
    text = raw.translate(DEVANAGARI_DIGITS).lower()
    text = text.replace("₹", " rs ")
    for phrase, rep in sorted(PHRASES.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(phrase, f" {rep} ")
    pq = ParsedQuery(raw=raw, text="", tokens=[])

    # price ranges: "1000 se 2000", "1000-2000", "between 1000 and 2000"
    m = re.search(rf"(?:between\s+)?(?:rs\s*)?{_NUM}\s*(?:-|to|se|and|से)\s*(?:rs\s*)?{_NUM}", text)
    if m and _num(m.group(1)) < _num(m.group(2)) and _num(m.group(1)) >= 100:
        pq.min_price, pq.max_price = _num(m.group(1)), _num(m.group(2))
    else:
        m = re.search(rf"(?:\blt\b|under|below|within|upto|max|budget|<)\s*(?:rs\s*)?{_NUM}", text) or \
            re.search(rf"(?:rs\s*)?{_NUM}\s*(?:rs\s*|rupees\s*|rupaye\s*|रुपये\s*)?(?:\blt\b|tak\b|तक|max\b)", text)
        if m:
            pq.max_price = _num(m.group(1))
        m = re.search(rf"(?:\bgt\b|above|over)\s*(?:rs\s*)?{_NUM}", text) or \
            re.search(rf"(?:rs\s*)?{_NUM}\s*(?:rs\s*)?\bgt\b", text)
        if m:
            pq.min_price = _num(m.group(1))

    # sizes
    m = re.search(r"\buk\s*(\d{1,2})\b", text) or re.search(r"\b(\d{1,2})\s*(?:number|no\.?)\b", text)
    if m:
        pq.size = f"UK{int(m.group(1))}"
    m2 = re.search(r"\b(?:size|waist)\s*(\d{2})\b|\b(\d{2})\s*(?:waist|size)\b", text)
    if not pq.size and m2:
        pq.size = m2.group(1) or m2.group(2)
    if not pq.size:
        m3 = re.search(r"\bsize\s*(xxl|2xl|xl|xs|small|medium|large|s|m|l)\b|\b(xxl|2xl|xl|xs|small|medium|large|s|m|l)\s*size\b", text) \
            or re.search(r"\b(xxl|2xl|xl|xs)\b", text)
        if m3:
            word = next(g for g in m3.groups() if g)
            pq.size = SIZE_WORDS[word]

    tokens: list[str] = []
    for tok in _tokenize(text):
        if tok.isdigit() or re.fullmatch(r"\d[\d,]*k?", tok) or re.fullmatch(r"uk\d+", tok):
            continue
        if tok in COLORS:
            pq.color = pq.color or COLORS[tok]
            continue
        if tok in STOPWORDS:
            continue
        if pq.size and tok.upper() == pq.size or (tok in SIZE_WORDS and pq.size == SIZE_WORDS[tok]):
            continue
        tokens.extend(LEXICON.get(tok, [tok]))
    pq.tokens = tokens

    toks = set(tokens)
    cats: list[str] = []
    for t in tokens:
        for c in CATEGORY_OF.get(t, []):
            if c not in cats:
                cats.append(c)
    if "jacket" in toks and not cats:
        if toks & {"rain", "waterproof", "monsoon"}:
            cats = ["rain jacket"]
        elif toks & {"warm", "winter"}:
            cats = ["winter jacket"]
        else:
            cats = ["rain jacket", "winter jacket"]
    if "kurta" in cats and "women" in toks and "kurti" not in cats:
        cats.append("kurti")
    pq.categories = cats
    if "women" in toks:
        pq.gender = "women"
    elif "men" in toks:
        pq.gender = "men"
    elif "kids" in toks:
        pq.gender = "kids"
    pq.text = " ".join(tokens)
    return pq

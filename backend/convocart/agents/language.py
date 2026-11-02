"""Language detection (en / hi / hinglish) and reply templates.

Templates are used by the scripted model, by guardrail fallbacks and by fixed system messages
(handover, step limit). Hindi and Hinglish strings need a native speaker's review before you
claim language support (docs/HANDOVER.md lists this as an open item).
"""
from __future__ import annotations

import re

HINGLISH_MARKERS = {
    "hai", "hain", "kya", "ke", "ka", "ki", "liye", "chahiye", "dikhao", "mujhe", "mera", "meri", "mere", "nahi",
    "nahin", "kab", "kaise", "kitna", "kitne", "accha", "achha", "haan", "han", "ji", "aur", "bhi", "karo", "kar",
    "wala", "wali", "mein", "tak", "yaar", "bhai", "abhi", "kyun", "jaldi", "wapas", "paisa", "paise", "batao",
    "bataiye", "dijiye", "chahte", "chahta", "chahti", "andar", "kam", "zyada", "thoda", "bahut", "sahi", "theek",
    "thik", "aaya", "aayega", "hua", "hogi", "hoga", "lena", "dena", "daal", "dalo", "lelo", "le", "lo", "koi",
    "kuch", "sasta", "mehenga", "na", "pehla", "pehli", "doosra", "dusra", "wale", "joote", "chhata", "barsaat", "baarish", "halki", "halka", "garam", "kurta",
}

_DEV = re.compile(r"[ऀ-ॿ]")
_LAT = re.compile(r"[A-Za-z]")


def devanagari_ratio(text: str) -> float:
    d, l = len(_DEV.findall(text)), len(_LAT.findall(text))
    return d / (d + l) if d + l else 0.0


def detect_language(text: str, previous: str | None = None) -> str:
    if devanagari_ratio(text) >= 0.3:
        return "hi"
    words = re.findall(r"[a-z]+", text.lower())
    hits = sum(1 for w in words if w in HINGLISH_MARKERS)
    if hits >= 2 or (hits == 1 and (len(words) <= 3 or previous == "hinglish")):
        return "hinglish"
    if previous and len(words) <= 3 and not re.search(r"\b(the|please|thanks|thank|what|where|when|is|are|my)\b",
                                                        text.lower()):
        return previous  # "ok", "M", "2" etc. keep the conversation's language
    return "en"


def looks_like(text: str, lang: str) -> bool:
    """Rough check that a reply is in the expected language (used for scoring, not blocking)."""
    r = devanagari_ratio(text)
    if lang == "hi":
        return r >= 0.3
    if lang == "en":
        return r < 0.05
    words = re.findall(r"[a-z]+", text.lower())
    return r < 0.05 and any(w in HINGLISH_MARKERS for w in words)


T: dict[str, dict[str, str]] = {
    "results_header": {
        "en": "Here are {n} options{budget}:",
        "hinglish": "Yeh rahe {n} options{budget}:",
        "hi": "ये रहे {n} विकल्प{budget}:",
    },
    "budget": {"en": " under ₹{max}", "hinglish": " ₹{max} ke andar", "hi": " ₹{max} से कम में"},
    "results_footer": {
        "en": "Tell me the number and your size, and I'll add it to your cart.",
        "hinglish": "Number aur size bataiye, main cart mein daal deta hoon.",
        "hi": "नंबर और साइज़ बताइए, मैं कार्ट में जोड़ दूँगा।",
    },
    "no_results": {
        "en": "I couldn't find anything in stock that matches{budget}.",
        "hinglish": "Iske liye{budget} abhi stock mein kuch nahi mila.",
        "hi": "इसके लिए{budget} अभी स्टॉक में कुछ नहीं मिला।",
    },
    "over_budget": {
        "en": "Closest options above your budget:",
        "hinglish": "Budget se thoda upar yeh options hain:",
        "hi": "बजट से थोड़ा ऊपर ये विकल्प हैं:",
    },
    "need_size": {
        "en": "Which size would you like for {title}? In stock: {sizes}.",
        "hinglish": "{title} ke liye kaunsa size chahiye? Stock mein: {sizes}.",
        "hi": "{title} के लिए कौन सा साइज़ चाहिए? स्टॉक में: {sizes}।",
    },
    "out_of_stock": {
        "en": "Sorry, that size or colour is out of stock. In stock: {sizes}.",
        "hinglish": "Sorry, yeh size ya colour stock mein nahi hai. Available: {sizes}.",
        "hi": "माफ़ कीजिए, यह साइज़ या रंग स्टॉक में नहीं है। उपलब्ध: {sizes}।",
    },
    "added": {
        "en": "Added {title} ({color}, {size}) to your cart. Cart total: ₹{total}.",
        "hinglish": "{title} ({color}, {size}) cart mein daal diya. Cart total: ₹{total}.",
        "hi": "{title} ({color}, {size}) कार्ट में जोड़ दिया। कार्ट का कुल: ₹{total}।",
    },
    "pick_first": {
        "en": "Which product? Search first and tell me the option number.",
        "hinglish": "Kaunsa product? Pehle search kar lijiye, phir option number bataiye.",
        "hi": "कौन सा प्रोडक्ट? पहले खोजिए, फिर विकल्प का नंबर बताइए।",
    },
    "discount_refused": {
        "en": "I can't give {asked}% off. The most I can offer on this cart is {max}%. Shall I apply {max}%?",
        "hinglish": "{asked}% discount nahi de sakta. Is cart par maximum {max}% de sakta hoon. {max}% laga doon?",
        "hi": "{asked}% छूट नहीं दे सकता। इस कार्ट पर ज़्यादा से ज़्यादा {max}% दे सकता हूँ। {max}% लगा दूँ?",
    },
    "discount_min_cart": {
        "en": "Discounts start on carts of ₹{min} or more. Your cart is ₹{subtotal}.",
        "hinglish": "Discount ₹{min} ya usse zyada ke cart par milta hai. Aapka cart ₹{subtotal} ka hai.",
        "hi": "छूट ₹{min} या उससे ज़्यादा के कार्ट पर मिलती है। आपका कार्ट ₹{subtotal} का है।",
    },
    "discount_empty": {
        "en": "Your cart is empty, so there's nothing to discount yet.",
        "hinglish": "Aapka cart khaali hai, abhi discount kis par lagaun?",
        "hi": "आपका कार्ट खाली है, अभी छूट किस पर लगाऊँ?",
    },
    "discount_applied": {
        "en": "Done, {pct}% off applied. New total: ₹{total} (you save ₹{amount}).",
        "hinglish": "Ho gaya, {pct}% discount lag gaya. Naya total: ₹{total} (₹{amount} ki bachat).",
        "hi": "हो गया, {pct}% छूट लग गई। नया कुल: ₹{total} (₹{amount} की बचत)।",
    },
    "discount_already": {
        "en": "Your cart already has {pct}% off, which is the most I can give.",
        "hinglish": "Aapke cart par pehle se {pct}% discount laga hai, isse zyada nahi de sakta.",
        "hi": "आपके कार्ट पर पहले से {pct}% छूट लगी है, इससे ज़्यादा नहीं दे सकता।",
    },
    "checkout": {
        "en": "Your cart total is ₹{total}. Pay securely here: {link}",
        "hinglish": "Aapka cart total ₹{total} hai. Yahan payment kijiye: {link}",
        "hi": "आपके कार्ट का कुल ₹{total} है। यहाँ भुगतान कीजिए: {link}",
    },
    "need_login": {
        "en": "Please sign in so I can see your account.",
        "hinglish": "Please sign in kijiye, tabhi main aapka account dekh paunga.",
        "hi": "कृपया साइन इन कीजिए, तभी मैं आपका खाता देख पाऊँगा।",
    },
    "cart": {
        "en": "Your cart:\n{lines}\nTotal: ₹{total}",
        "hinglish": "Aapka cart:\n{lines}\nTotal: ₹{total}",
        "hi": "आपका कार्ट:\n{lines}\nकुल: ₹{total}",
    },
    "cart_empty": {"en": "Your cart is empty.", "hinglish": "Aapka cart khaali hai.", "hi": "आपका कार्ट खाली है।"},
    "details": {
        "en": "{title}: ₹{price}{mrp}. {weight} g. Features: {tags}. Rated {rating}/5. In stock sizes: {sizes}.",
        "hinglish": "{title}: ₹{price}{mrp}. Weight {weight} g. Features: {tags}. Rating {rating}/5. Stock mein sizes: {sizes}.",
        "hi": "{title}: ₹{price}{mrp}। वज़न {weight} ग्राम। खूबियाँ: {tags}। रेटिंग {rating}/5। स्टॉक में साइज़: {sizes}।",
    },
    "order_paid": {
        "en": "Order {id} is confirmed and being packed. Total ₹{total}.",
        "hinglish": "Order {id} confirm ho gaya hai aur pack ho raha hai. Total ₹{total}.",
        "hi": "ऑर्डर {id} कन्फ़र्म है और पैक हो रहा है। कुल ₹{total}।",
    },
    "order_shipped": {
        "en": "Order {id} has shipped with {courier}. Tracking ID: {tracking}.",
        "hinglish": "Order {id} {courier} se ship ho chuka hai. Tracking ID: {tracking}.",
        "hi": "ऑर्डर {id} {courier} से भेज दिया गया है। ट्रैकिंग आईडी: {tracking}।",
    },
    "order_delivered": {
        "en": "Order {id} was delivered on {date}.",
        "hinglish": "Order {id} {date} ko deliver ho gaya tha.",
        "hi": "ऑर्डर {id} {date} को डिलीवर हो गया था।",
    },
    "order_returned": {
        "en": "Order {id} has been returned.", "hinglish": "Order {id} return ho chuka hai.",
        "hi": "ऑर्डर {id} वापस हो चुका है।",
    },
    "order_cancelled": {
        "en": "Order {id} was cancelled.", "hinglish": "Order {id} cancel ho gaya tha.", "hi": "ऑर्डर {id} रद्द हो गया था।",
    },
    "order_not_found": {
        "en": "I couldn't find order {id} on your account. Please check the number.",
        "hinglish": "Aapke account mein order {id} nahi mila. Number ek baar check kar lijiye.",
        "hi": "आपके खाते में ऑर्डर {id} नहीं मिला। कृपया नंबर जाँच लीजिए।",
    },
    "orders_list": {
        "en": "Your recent orders:\n{lines}\nWhich one is this about?",
        "hinglish": "Aapke recent orders:\n{lines}\nKis order ke baare mein baat karni hai?",
        "hi": "आपके हाल के ऑर्डर:\n{lines}\nकिस ऑर्डर के बारे में बात करनी है?",
    },
    "no_orders": {"en": "I don't see any orders on your account.", "hinglish": "Aapke account mein koi order nahi hai.",
                  "hi": "आपके खाते में कोई ऑर्डर नहीं है।"},
    "return_created": {
        "en": "Return {rid} is booked for order {id}. A courier will pick it up in 2-3 days.",
        "hinglish": "Order {id} ka return {rid} book ho gaya. 2-3 din mein courier pickup karega.",
        "hi": "ऑर्डर {id} की वापसी {rid} बुक हो गई। 2-3 दिन में कूरियर पिकअप करेगा।",
    },
    "exchange_created": {
        "en": "Exchange {rid} is booked for order {id}{size}. We'll pick up the old one and send the new one.",
        "hinglish": "Order {id} ka exchange {rid} book ho gaya{size}. Purana pickup karke naya bhej denge.",
        "hi": "ऑर्डर {id} का एक्सचेंज {rid} बुक हो गया{size}। पुराना लेकर नया भेज देंगे।",
    },
    "refund_pending": {
        "en": "Refund request {rid} for order {id} (₹{amount}) is with our team for approval. You'll hear back within 24 hours.",
        "hinglish": "Order {id} ke refund (₹{amount}) ki request {rid} team ke paas approval ke liye hai. 24 ghante mein update milega.",
        "hi": "ऑर्डर {id} के रिफ़ंड (₹{amount}) का अनुरोध {rid} टीम के पास मंज़ूरी के लिए है। 24 घंटे में जवाब मिलेगा।",
    },
    "refund_done": {
        "en": "Refund {rid} for order {id} (₹{amount}) is processed.",
        "hinglish": "Order {id} ka refund {rid} (₹{amount}) process ho gaya.",
        "hi": "ऑर्डर {id} का रिफ़ंड {rid} (₹{amount}) हो गया।",
    },
    "return_window": {
        "en": "Order {id} was delivered more than {days} days ago, so it's outside the return window.",
        "hinglish": "Order {id} {days} din se pehle deliver hua tha, isliye return window band ho chuki hai.",
        "hi": "ऑर्डर {id} {days} दिन से पहले डिलीवर हुआ था, इसलिए वापसी की अवधि खत्म हो चुकी है।",
    },
    "return_not_delivered": {
        "en": "Order {id} hasn't been delivered yet, so a return can't be started.",
        "hinglish": "Order {id} abhi deliver nahi hua hai, isliye return shuru nahi ho sakta.",
        "hi": "ऑर्डर {id} अभी डिलीवर नहीं हुआ है, इसलिए वापसी शुरू नहीं हो सकती।",
    },
    "return_exists": {
        "en": "There's already an open request for order {id}.",
        "hinglish": "Order {id} ke liye pehle se ek request khuli hai.",
        "hi": "ऑर्डर {id} के लिए पहले से एक अनुरोध खुला है।",
    },
    "ask_order": {
        "en": "Which order is this about? Please share the order number (like ORD-10001).",
        "hinglish": "Kaunsa order? Order number bataiye (jaise ORD-10001).",
        "hi": "कौन सा ऑर्डर? ऑर्डर नंबर बताइए (जैसे ORD-10001)।",
    },
    "handover": {
        "en": "I'm passing this to a member of our team. They can see this conversation, so you won't need to repeat yourself.",
        "hinglish": "Main aapko hamari team ke ek member se connect kar raha hoon. Unhe yeh poori baatcheet dikhegi, aapko dobara batana nahi padega.",
        "hi": "मैं आपको हमारी टीम के एक सदस्य से जोड़ रहा हूँ। उन्हें यह पूरी बातचीत दिखेगी, आपको दोबारा बताना नहीं पड़ेगा।",
    },
    "with_human": {
        "en": "A team member has your conversation and will reply here shortly.",
        "hinglish": "Team member aapki baatcheet dekh rahe hain, thodi der mein yahin reply karenge.",
        "hi": "टीम का सदस्य आपकी बातचीत देख रहा है, थोड़ी देर में यहीं जवाब देगा।",
    },
    "fallback": {
        "en": "Sorry, I didn't get that. I can find products, build your cart, check an order or start a return.",
        "hinglish": "Sorry, samajh nahi aaya. Main product dhoondh sakta hoon, cart bana sakta hoon, order check ya return shuru kar sakta hoon.",
        "hi": "माफ़ कीजिए, समझ नहीं आया। मैं प्रोडक्ट खोज सकता हूँ, कार्ट बना सकता हूँ, ऑर्डर देख सकता हूँ या वापसी शुरू कर सकता हूँ।",
    },
    "error": {
        "en": "Something went wrong on our side. Please try again in a minute.",
        "hinglish": "Hamari taraf se kuch gadbad ho gayi. Ek minute baad dobara try kijiye.",
        "hi": "हमारी तरफ़ से कुछ गड़बड़ हो गई। एक मिनट बाद फिर कोशिश कीजिए।",
    },
    "recovery": {
        "en": "Hi {name}, your Kesar Lane cart is still waiting: {item}{more}, total ₹{total}. Pick up where you left off in our chat: {link}",
        "hinglish": "Hi {name}, aapka Kesar Lane cart abhi bhi wait kar raha hai: {item}{more}, total ₹{total}. Chat mein wahin se shuru kijiye: {link}",
        "hi": "नमस्ते {name}, आपका Kesar Lane कार्ट अभी भी इंतज़ार कर रहा है: {item}{more}, कुल ₹{total}। चैट में वहीं से शुरू कीजिए: {link}",
    },
    "recovery_discount": {
        "en": "Hi {name}, the {pct}% off you got in our chat is still on your cart: {item}{more}, now ₹{total}. Finish your order here: {link}",
        "hinglish": "Hi {name}, chat mein mila {pct}% off abhi bhi aapke cart par hai: {item}{more}, ab sirf ₹{total}. Order yahan poora kijiye: {link}",
        "hi": "नमस्ते {name}, चैट में मिली {pct}% की छूट अभी भी आपके कार्ट पर है: {item}{more}, अब ₹{total}। ऑर्डर यहाँ पूरा कीजिए: {link}",
    },
    "unsubscribe_line": {
        "en": "Don't want these emails? Unsubscribe: {link}",
        "hinglish": "Yeh emails nahi chahiye? Unsubscribe: {link}",
        "hi": "ये ईमेल नहीं चाहिए? अनसब्सक्राइब: {link}",
    },
    "recovery_subject_discount": {
        "en": "Your {pct}% off is still waiting at Kesar Lane",
        "hinglish": "Aapka {pct}% off abhi bhi wait kar raha hai",
        "hi": "आपकी {pct}% छूट अभी भी इंतज़ार कर रही है",
    },
    "discount_word": {"en": "Discount", "hinglish": "Discount", "hi": "छूट"},
    "order_subject": {
        "en": "Order {id} received, thank you!",
        "hinglish": "Order {id} mil gaya, shukriya!",
        "hi": "ऑर्डर {id} मिल गया, धन्यवाद!",
    },
    "order_confirmation": {
        "en": "Hi {name},\n\nThank you for shopping with Kesar Lane. We've received your order {id}.\n\n{lines}\nTotal paid: ₹{total}\n\nWe'll pack it soon. To track it, ask our chat \"where is {id}?\": {link}",
        "hinglish": "Hi {name},\n\nKesar Lane se shopping ke liye shukriya. Aapka order {id} humein mil gaya hai.\n\n{lines}\nTotal paid: ₹{total}\n\nJald hi pack karenge. Track karne ke liye chat mein poochiye \"{id} kahan hai?\": {link}",
        "hi": "नमस्ते {name},\n\nKesar Lane से खरीदारी के लिए धन्यवाद। आपका ऑर्डर {id} हमें मिल गया है।\n\n{lines}\nकुल भुगतान: ₹{total}\n\nहम जल्द ही पैक करेंगे। ट्रैक करने के लिए चैट में पूछिए \"{id} कहाँ है?\": {link}",
    },
    "more_items": {"en": " and {n} more", "hinglish": " aur {n} aur items", "hi": " और {n} अन्य चीज़ें"},
    "recovery_subject": {
        "en": "You left something in your Kesar Lane cart",
        "hinglish": "Aapka Kesar Lane cart aapka intezaar kar raha hai",
        "hi": "आपका Kesar Lane कार्ट आपका इंतज़ार कर रहा है",
    },
}


def t(key: str, lang: str, **kw) -> str:
    table = T[key]
    return table.get(lang, table["en"]).format(**kw)

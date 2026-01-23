from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic
import os
import re
from collections import defaultdict
from datetime import datetime
import requests
import time

app = Flask(__name__)
CORS(app)

# ==================== CONFIGURATION ====================
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY')
SHOPIFY_CLIENT_ID = os.environ.get('SHOPIFY_CLIENT_ID')
SHOPIFY_CLIENT_SECRET = os.environ.get('SHOPIFY_CLIENT_SECRET')
SHOPIFY_SHOP_URL = os.environ.get('SHOPIFY_SHOP_URL', '792489-4.myshopify.com')

# Token cache
shopify_token_cache = {
    'access_token': None,
    'expires_at': 0
}

def get_shopify_token():
    """Get a valid Shopify access token, refreshing if needed"""
    if shopify_token_cache['access_token'] and time.time() < shopify_token_cache['expires_at'] - 300:
        return shopify_token_cache['access_token']
    
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        print("DEBUG: Missing SHOPIFY_CLIENT_ID or SHOPIFY_CLIENT_SECRET")
        return None
    
    try:
        print("DEBUG: Requesting new Shopify access token...")
        response = requests.post(
            f'https://{SHOPIFY_SHOP_URL}/admin/oauth/access_token',
            data={
                'grant_type': 'client_credentials',
                'client_id': SHOPIFY_CLIENT_ID,
                'client_secret': SHOPIFY_CLIENT_SECRET
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            shopify_token_cache['access_token'] = data['access_token']
            shopify_token_cache['expires_at'] = time.time() + data.get('expires_in', 86399)
            print("DEBUG: Got new Shopify token successfully")
            return data['access_token']
        else:
            print(f"DEBUG: Token error: {response.text}")
            return None
    except Exception as e:
        print(f"DEBUG: Token exception: {e}")
        return None

# ==================== CONVERSATION STORAGE ====================
conversations = []

def log_conversation(user_message, bot_response, language='fr'):
    conversations.append({
        'timestamp': datetime.now().isoformat(),
        'user_message': user_message,
        'bot_response': bot_response,
        'language': language
    })

# ==================== FAQ DATA ====================
FAQ_DATA = [
    {
        'content': 'Marakame est une boutique suisse proposant des bijoux et accessoires artisanaux faits main. Nos créations incluent des boucles d\'oreilles, bagues, colliers, bracelets Wayuu et sacs Wayuu. Chaque pièce est unique, fabriquée par des artisanes au Mexique ou en Colombie selon le produit (l\'origine est indiquée sur chaque page produit).',
        'content_en': 'Marakame is a Swiss boutique offering handmade artisanal jewelry and accessories. Our creations include earrings, rings, necklaces, Wayuu bracelets and Wayuu bags. Each piece is unique, made by artisans in Mexico or Colombia depending on the product (origin is indicated on each product page).',
        'content_es': 'Marakame es una boutique suiza que ofrece joyas y accesorios artesanales hechos a mano. Nuestras creaciones incluyen aretes, anillos, collares, pulseras Wayuu y bolsos Wayuu. Cada pieza es única, fabricada por artesanas en México o Colombia según el producto (el origen se indica en cada página de producto).',
        'content_de': 'Marakame ist eine Schweizer Boutique für handgefertigten Schmuck und Accessoires. Unsere Kreationen umfassen Ohrringe, Ringe, Halsketten, Wayuu-Armbänder und Wayuu-Taschen. Jedes Stück ist einzigartig, hergestellt von Kunsthandwerkerinnen in Mexiko oder Kolumbien (die Herkunft ist auf jeder Produktseite angegeben).',
        'content_it': 'Marakame è una boutique svizzera che offre gioielli e accessori artigianali fatti a mano. Le nostre creazioni includono orecchini, anelli, collane, braccialetti Wayuu e borse Wayuu. Ogni pezzo è unico, realizzato da artigiane in Messico o Colombia a seconda del prodotto (l\'origine è indicata su ogni pagina prodotto).',
        'category': 'about',
        'keywords': ['marakame', 'bijoux', 'jewelry', 'accessoires', 'artisan', 'mexique', 'colombie', 'wayuu', 'boucles', 'bagues', 'colliers']
    },
    {
        'content': 'Livraison en Suisse: gratuite dès 50 CHF, délai de 2-4 jours ouvrables. Livraison internationale (France, Allemagne, etc.): 5-10 jours ouvrables, frais calculés à la commande.',
        'content_en': 'Delivery in Switzerland: free from 50 CHF, 2-4 business days. International delivery (France, Germany, etc.): 5-10 business days, fees calculated at checkout.',
        'content_es': 'Envío en Suiza: gratis desde 50 CHF, 2-4 días hábiles. Envío internacional (Francia, Alemania, etc.): 5-10 días hábiles, gastos calculados al realizar el pedido.',
        'content_de': 'Lieferung in der Schweiz: kostenlos ab 50 CHF, 2-4 Werktage. Internationale Lieferung (Frankreich, Deutschland, etc.): 5-10 Werktage, Gebühren werden bei der Bestellung berechnet.',
        'content_it': 'Consegna in Svizzera: gratuita da 50 CHF, 2-4 giorni lavorativi. Consegna internazionale (Francia, Germania, ecc.): 5-10 giorni lavorativi, spese calcolate al momento dell\'ordine.',
        'category': 'livraison',
        'keywords': ['livraison', 'delivery', 'shipping', 'suisse', 'swiss', 'international', 'france', 'délai', 'jours']
    },
    {
        'content': 'Modes de paiement acceptés: carte de crédit (Visa, Mastercard, American Express), PayPal, Twint, et virement bancaire. Tous les paiements sont 100% sécurisés.',
        'content_en': 'Accepted payment methods: credit card (Visa, Mastercard, American Express), PayPal, Twint, and bank transfer. All payments are 100% secure.',
        'content_es': 'Métodos de pago aceptados: tarjeta de crédito (Visa, Mastercard, American Express), PayPal, Twint y transferencia bancaria. Todos los pagos son 100% seguros.',
        'content_de': 'Akzeptierte Zahlungsmethoden: Kreditkarte (Visa, Mastercard, American Express), PayPal, Twint und Banküberweisung. Alle Zahlungen sind 100% sicher.',
        'content_it': 'Metodi di pagamento accettati: carta di credito (Visa, Mastercard, American Express), PayPal, Twint e bonifico bancario. Tutti i pagamenti sono sicuri al 100%.',
        'category': 'paiement',
        'keywords': ['paiement', 'payment', 'carte', 'credit', 'paypal', 'twint', 'visa', 'mastercard']
    },
    {
        'content': 'Retours acceptés sous 30 jours après réception. Le produit doit être dans son état original avec emballage. Contactez info@marakame.ch pour initier un retour. Remboursement sous 5-7 jours après réception.',
        'content_en': 'Returns accepted within 30 days of receipt. Product must be in original condition with packaging. Contact info@marakame.ch to initiate a return. Refund within 5-7 days after receipt.',
        'content_es': 'Devoluciones aceptadas dentro de los 30 días posteriores a la recepción. El producto debe estar en su estado original con embalaje. Contacte info@marakame.ch para iniciar una devolución.',
        'content_de': 'Rücksendungen werden innerhalb von 30 Tagen nach Erhalt akzeptiert. Das Produkt muss sich im Originalzustand mit Verpackung befinden. Kontaktieren Sie info@marakame.ch für eine Rücksendung.',
        'content_it': 'Resi accettati entro 30 giorni dalla ricezione. Il prodotto deve essere nelle condizioni originali con imballaggio. Contattare info@marakame.ch per avviare un reso.',
        'category': 'retours',
        'keywords': ['retour', 'return', 'remboursement', 'refund', '30 jours', 'échange']
    },
    {
        'content': 'Nos bijoux (boucles d\'oreilles, bagues, colliers) sont fabriqués avec des matériaux de qualité par des artisanes. L\'origine (Mexique ou Colombie) est indiquée sur chaque page produit sous "Made in". Les bracelets et sacs Wayuu sont tissés à la main par des artisanes colombiennes de la communauté Wayuu.',
        'content_en': 'Our jewelry (earrings, rings, necklaces) is crafted with quality materials by artisans. The origin (Mexico or Colombia) is indicated on each product page under "Made in". Wayuu bracelets and bags are hand-woven by Colombian artisans from the Wayuu community.',
        'content_es': 'Nuestras joyas (aretes, anillos, collares) están fabricadas con materiales de calidad por artesanas. El origen (México o Colombia) se indica en cada página de producto bajo "Made in". Las pulseras y bolsos Wayuu son tejidos a mano por artesanas colombianas de la comunidad Wayuu.',
        'content_de': 'Unser Schmuck (Ohrringe, Ringe, Halsketten) wird von Kunsthandwerkerinnen aus hochwertigen Materialien gefertigt. Die Herkunft (Mexiko oder Kolumbien) ist auf jeder Produktseite unter "Made in" angegeben. Wayuu-Armbänder und -Taschen werden von kolumbianischen Kunsthandwerkerinnen der Wayuu-Gemeinschaft handgewebt.',
        'content_it': 'I nostri gioielli (orecchini, anelli, collane) sono realizzati con materiali di qualità da artigiane. L\'origine (Messico o Colombia) è indicata su ogni pagina prodotto sotto "Made in". I braccialetti e le borse Wayuu sono tessuti a mano da artigiane colombiane della comunità Wayuu.',
        'category': 'produits',
        'keywords': ['bijoux', 'jewelry', 'boucles', 'earrings', 'bagues', 'rings', 'colliers', 'necklaces', 'wayuu', 'sac', 'bag', 'bracelet', 'mexique', 'colombie']
    },
    {
        'content': 'Entretien des bijoux: évitez le contact prolongé avec l\'eau, les parfums et produits chimiques. Rangez-les dans une pochette pour préserver leur éclat. Nettoyez délicatement avec un chiffon doux si nécessaire.',
        'content_en': 'Jewelry care: avoid prolonged contact with water, perfumes and chemicals. Store in a pouch to preserve their shine. Gently clean with a soft cloth if necessary.',
        'content_es': 'Cuidado de las joyas: evite el contacto prolongado con agua, perfumes y productos químicos. Guárdelas en una bolsa para preservar su brillo. Limpie suavemente con un paño suave si es necesario.',
        'content_de': 'Schmuckpflege: Vermeiden Sie längeren Kontakt mit Wasser, Parfüms und Chemikalien. In einem Beutel aufbewahren, um den Glanz zu erhalten. Bei Bedarf vorsichtig mit einem weichen Tuch reinigen.',
        'content_it': 'Cura dei gioielli: evitare il contatto prolungato con acqua, profumi e prodotti chimici. Conservare in una custodia per preservare la lucentezza. Pulire delicatamente con un panno morbido se necessario.',
        'category': 'entretien',
        'keywords': ['entretien', 'care', 'nettoyage', 'eau', 'water', 'rangement']
    },
    {
        'content': 'Pour suivre votre commande, connectez-vous à votre compte sur marakame.ch ou utilisez le lien de suivi envoyé par email. Si vous n\'avez pas reçu d\'email, vérifiez vos spams ou contactez info@marakame.ch.',
        'content_en': 'To track your order, log in to your account on marakame.ch or use the tracking link sent by email. If you haven\'t received an email, check your spam folder or contact info@marakame.ch.',
        'content_es': 'Para rastrear su pedido, inicie sesión en su cuenta en marakame.ch o use el enlace de seguimiento enviado por correo electrónico.',
        'content_de': 'Um Ihre Bestellung zu verfolgen, melden Sie sich bei Ihrem Konto auf marakame.ch an oder verwenden Sie den per E-Mail gesendeten Tracking-Link.',
        'content_it': 'Per tracciare il tuo ordine, accedi al tuo account su marakame.ch o usa il link di tracciamento inviato via email.',
        'category': 'commande',
        'keywords': ['commande', 'order', 'suivi', 'tracking', 'email', 'compte']
    },
]

# ==================== LANGUAGE DETECTION ====================
def detect_language(text):
    text_lower = text.lower()
    
    fr_words = ['bonjour', 'merci', 'commande', 'livraison', 'comment', 'quand', 'où', 'pourquoi', 'je', 'mon', 'ma', 'une', 'des', 'les', 'pour', 'avec']
    en_words = ['hello', 'hi', 'thanks', 'order', 'delivery', 'how', 'when', 'where', 'what', 'my', 'the', 'is', 'are', 'can', 'could']
    es_words = ['hola', 'gracias', 'pedido', 'envío', 'cómo', 'cuándo', 'dónde', 'qué', 'mi', 'una', 'el', 'la']
    de_words = ['hallo', 'danke', 'bestellung', 'lieferung', 'wie', 'wann', 'wo', 'mein', 'der', 'die', 'das']
    it_words = ['ciao', 'grazie', 'ordine', 'consegna', 'come', 'quando', 'dove', 'mio', 'il', 'la']
    
    scores = {
        'fr': sum(1 for w in fr_words if w in text_lower),
        'en': sum(1 for w in en_words if w in text_lower),
        'es': sum(1 for w in es_words if w in text_lower),
        'de': sum(1 for w in de_words if w in text_lower),
        'it': sum(1 for w in it_words if w in text_lower)
    }
    
    max_score = max(scores.values())
    if max_score == 0:
        return 'fr'
    return max(scores, key=scores.get)

# ==================== RAG MULTILINGUE ====================
class MultilingualRAG:
    def __init__(self):
        self.documents = []
        self.index = defaultdict(list)
    
    def add_documents(self, docs):
        for doc in docs:
            doc_id = len(self.documents)
            self.documents.append(doc)
            keywords = doc.get('keywords', [])
            for kw in keywords:
                self.index[kw.lower()].append(doc_id)
            for lang_key in ['content', 'content_en', 'content_es', 'content_de', 'content_it']:
                if lang_key in doc:
                    words = self._tokenize(doc[lang_key])
                    for word in set(words):
                        if len(word) > 2:
                            self.index[word].append(doc_id)
    
    def _tokenize(self, text):
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        return text.split()
    
    def search(self, query, language='fr', top_k=3):
        query_words = self._tokenize(query)
        scores = defaultdict(float)
        
        for word in query_words:
            if word in self.index:
                for doc_id in self.index[word]:
                    scores[doc_id] += 1
        
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        results = []
        lang_key = f'content_{language}' if language != 'fr' else 'content'
        
        for doc_id, score in ranked[:top_k]:
            doc = self.documents[doc_id]
            content = doc.get(lang_key, doc.get('content', ''))
            results.append({
                'content': content,
                'category': doc.get('category', ''),
                'score': score
            })
        return results

rag = MultilingualRAG()
rag.add_documents(FAQ_DATA)

# ==================== SHOPIFY ====================
def get_shopify_order(order_id_or_email):
    token = get_shopify_token()
    if not token:
        print("DEBUG: Could not get Shopify token")
        return None
    
    print(f"DEBUG: Searching for order: {order_id_or_email}")
    
    headers = {
        'X-Shopify-Access-Token': token,
        'Content-Type': 'application/json'
    }
    
    try:
        if '@' in order_id_or_email:
            url = f'https://{SHOPIFY_SHOP_URL}/admin/api/2024-01/orders.json?email={order_id_or_email}&status=any'
        else:
            order_num = order_id_or_email.replace('#', '').replace('MK', '').strip()
            url = f'https://{SHOPIFY_SHOP_URL}/admin/api/2024-01/orders.json?name=%23{order_num}&status=any'
        
        print(f"DEBUG: Calling URL: {url}")
        response = requests.get(url, headers=headers, timeout=10)
        print(f"DEBUG: Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('orders'):
                print(f"DEBUG: Found {len(data['orders'])} orders")
                return data['orders'][0]
            else:
                print("DEBUG: No orders found in response")
        else:
            print(f"DEBUG: Error response: {response.text[:200]}")
    except Exception as e:
        print(f"DEBUG: Shopify exception: {e}")
    return None

def format_order_info(order, language='fr'):
    if not order:
        return None
    
    status_map = {
        'fr': {'fulfilled': 'Expédiée', 'unfulfilled': 'En préparation', 'partially_fulfilled': 'Partiellement expédiée'},
        'en': {'fulfilled': 'Shipped', 'unfulfilled': 'Processing', 'partially_fulfilled': 'Partially shipped'},
    }
    
    status = order.get('fulfillment_status') or 'unfulfilled'
    status_text = status_map.get(language, status_map['fr']).get(status, status)
    
    return {
        'order_number': order.get('name', ''),
        'status': status_text,
        'total': f"{order.get('total_price', '0')} {order.get('currency', 'CHF')}",
        'created_at': order.get('created_at', '')[:10]
    }

# ==================== TAIYARI PROMPT ====================
def get_taiyari_prompt(language, context):
    prompts = {
        'fr': f"""Tu es Taiyari, l'assistant virtuel de Marakame, une boutique suisse de bijoux et accessoires artisanaux.

PRODUITS MARAKAME:
- Bijoux: boucles d'oreilles, bagues, colliers
- Accessoires: bracelets Wayuu, sacs Wayuu
- Fabriqués par des artisanes au Mexique ou en Colombie (voir "Made in" sur chaque page produit)

PERSONNALITÉ:
- Chaleureux, amical et professionnel
- Utilise des expressions naturelles: "Hmm...", "Voyons voir...", "Ah !"
- Concis et direct (2-3 phrases max)
- Emojis avec parcimonie (1-2 max)
- Vouvoie les clients

RÈGLES STRICTES:
1. NE JAMAIS utiliser le mot "Huichol" - dire "artisanes mexicaines" ou "artisanes colombiennes" selon l'origine
2. Réponds UNIQUEMENT avec le contexte fourni
3. Ne jamais inventer d'information
4. Pour l'origine d'un produit, toujours référer à la page produit (Made in Mexico ou Made in Colombia)
5. Si pas d'info: "Hmm, je n'ai pas cette information. Souhaitez-vous que notre équipe vous recontacte à info@marakame.ch ?"
6. Pour les commandes, demande le numéro ou l'email

CONTEXTE:
{context}""",

        'en': f"""You are Taiyari, the virtual assistant for Marakame, a Swiss boutique selling artisanal jewelry and accessories.

MARAKAME PRODUCTS:
- Jewelry: earrings, rings, necklaces
- Accessories: Wayuu bracelets, Wayuu bags
- Made by artisans in Mexico or Colombia (see "Made in" on each product page)

PERSONALITY:
- Warm, friendly and professional
- Use natural expressions: "Hmm...", "Let me see...", "Ah!"
- Concise and direct (2-3 sentences max)
- Emojis sparingly (1-2 max)

STRICT RULES:
1. NEVER use the word "Huichol" - say "Mexican artisans" or "Colombian artisans" depending on origin
2. Answer ONLY with provided context
3. Never make up information
4. For product origin, always refer to the product page (Made in Mexico or Made in Colombia)
5. If no info: "Hmm, I don't have that information. Would you like our team to contact you at info@marakame.ch?"
6. For orders, ask for number or email

CONTEXT:
{context}"""
    }
    return prompts.get(language, prompts['fr'])

# ==================== LOGO BASE64 ====================
LOGO_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAFAAAABQCAYAAACOEfKtAAABAGlDQ1BpY2MAABiVY2BgPMEABCwGDAy5eSVFQe5OChGRUQrsDxgYgRAMEpOLCxhwA6Cqb9cgai/r4lGHC3CmpBYnA+kPQKxSBLQcaKQIkC2SDmFrgNhJELYNiF1eUlACZAeA2EUhQc5AdgqQrZGOxE5CYicXFIHU9wDZNrk5pckIdzPwpOaFBgNpDiCWYShmCGJwZ3AC+R+iJH8RA4PFVwYG5gkIsaSZDAzbWxkYJG4hxFQWMDDwtzAwbDuPEEOESUFiUSJYiAWImdLSGBg+LWdg4I1kYBC+wMDAFQ0LCBxuUwC7zZ0hHwjTGXIYUoEingx5DMkMekCWEYMBgyGDGQCm1j8/yRb+6wAAACBjSFJNAAB6JgAAgIQAAPoAAACA6AAAdTAAAOpgAAA6mAAAF3CculE8AAAABmJLR0QA/wD/AP+gvaeTAAAAB3RJTUUH6gEXCg4G8dLZvwAAC81JREFUeNrtnHuUnVV5xn/PPmcuJJMwMxmBBJKYC2hA07RqQwyGUEgXiKBguaWQhECFhVoRorbgrRWhC8RSKqiI4bYUEEO4lJqlJgRzGRIBWRIuSmJCoIyQZC65ze2c7+kfe08ysbSFmDkTh/PMmnXO2WfO2ft7vud9997vu9+BMsooo4wyyiijjDLKKKOMMsooo4y3gNx+Nh4Bo9NjR2qrBUYCrcCBQBHI3u4EChgCjAEKQGdqPwD4PlAHPJ7ajgXOANqBecAqYHt6rzJdQ/HtpvwRwI+AR4DvAvWpfTjwG2BJIhhgFvAgsBA4sdd35IGvApf054WEEvVTAQzr1V87UAV8DehKKgM4FHgeaAHel9oOBj4M/ARY1es7ZwCXAYf0aqvp5QIGFIFHAfcAR6fXLcAaYFoy28rUPho4CGgATk5tDcBqYGwvlzMCmJ3MeWuvfuYCV6cbNqAIbAXGATcCf5HalgMXAhMTSaS/WZ/Me0xS1yDgOuCdvZT698B4YAu7/eFRwOVAc1J1njj5lIzMfYl64IJexFQnBf5bMsWjkr9bCJwEfDuRNQ14VzLBI4HBwITkD6cAxwGHEyeaTwG/BM5NyrwZeBU4Pyl6XvKlh/0pEngw8BRwUyIBosNfksxxQVLH6cnvDX0LSqkiLm0ALgamE2fpu9NNOjORuRP4Crtn/Jr9nbRAXKfl0+urknl9Kb33ceCnyTQ/2EudfwwqE/HnJJ/ZCDwGPAz8LN3IOuJMf8s+6nMP7Mt14NB05ycD64CNyVTr08CXEyeP5em9nfugz55F9RqgDXg38B/AqGTm65LbOAj4r+RvlwPeHwnsSr7ui8mvFZJ5PpgIXEZcHJu+wc7kX7Nkso8AX04K7QS+l/pv29/N+JPASuAG4DngiuSHVMIx5JP/u5fogxuIy6V9jn29lTPwdDKZocA/JjK3lfAmOqkwI04wG4iL80JfdNZXqhgCnAAsZs+F7ptGfeOtCOWxK+jo6ihUBbdNvfitfs0H0jWu7qu7VbItz/+H6p9/DYUqQRXjDuly0/aG4Cz3aezp4MsRv8tlCpmEwqAs62im+dhP9Pu4+53A+lV3gZQjy94P/ggwEnyf0GugB41HANeTcY0C/0Dcxq00uj8QmjrdwbYpF/bb+EO/ktd4G6FzR1CWzRV+SPBFwenBZIa/szwCCcFMAuMNhxhmGv07+N6MwnsqQgUHL5/fb9eQL3WHdavuQCBDdUahU/kDasEnWnF3IbPaok1wChYIHLd9H5ZZiDjLOCc4BDSxrbZuzYHNzYPrG+8oEtxB+yCap585cBUogzLeJ7MwOP99Bz5mfA322TLLDE8YHQEaveszEsBU4Y3A04Iv2JxtvGNoS8s3kRYhfbVo5bPq9oGtQACL4cBxkiptz0JaL3M7cDGmCzHNmMjbLjetjOwlEWZbmiS42WgSUAVC0FqRKbjEXr2kCqxfdishHxB+QfB7R3UFoXHAPwPnP3FL1TpS0MEGG7C3AXdK+U3ASJmbQJOFqpI6AVa1V9HVmVVo+GM/Kp1FlaqjYY/fAVBtNBtnz0i6FHRGzwgMyH4ul3FyITDBcHCA9xqGCZYa7wDWCJ2LuMJRdfGzditwumCsYbWlZ0IxY8sH5wwMBTasuJMsB4bzgBuRTgEeAHcb4ygzLHYUgqaAFgg+mdnXEHJzDAXQvaBvgDqw2LWlNggtwWwD/klws+xDHUqjjZIQmAWjAvWCC4QrBWcBGy0eEEISQp2Y+4SfUQyUPhXEcWTFK8AFUhuwALwaY2Is/9bwrxJ/Y3So4Rjg40jUN/b98qYkk0hy7MOBsYriqTX8NXBZMEuDPaogPYtZYPwOie8YfiV0i+BDoIsMnweGFCmsC86di5iBKQK/kLMKpBMUc8nVhvcXi50hhHw2IAhMxtQFWo69BHgc3Iq1iY7N3y5UDfsMMBfRBPpboznCnzPcBWwEPwu6VvBnOcLZ4ClGfw7MO6Zy1vMrOm8bjcPFiAZilLvFoaLP4mYlJzAzgNYLfwY4WuKzoPHAi8Xq+huAaeDpiAdlngX/2jH1WQdsBx0mtA4Ihm2IExSTU5NWdN11GsqfY9wtWAG+x2hNRTHLuvP5/+1+vpGDNHsRq9wbT1sJHEEMnjp9RwvwuzcawLDG+WBXOORPAi4FpgpVItLkocXgq4F3hswdQAVolQNfBs6JHahF+BLZr2ZiAqgNjAjDLf4FU4lIax5aDfeDv5EP4fmOQsbWPWfjamKeuYEY8grEZNQi9iLktTcKzBE39IMTYSG1rX8jAjMFhKYCdwC1cdmWaJHATAEV7OJDDmEpMBbzOcNUlJbIuC4z05AORJoJvnL70Lqrh7S1/tBE8oRAwlAre65RQ3cxOyuvXWdsetAFPJquvUcAXezl8ZC9IbCdmBx6kxIXiA1p0CcbVWqPCcbbMJ1Gg4ClwHqJp4FNoFG97sh6oFVmtNFva1rb6oC16tlZ72GJrBU8EIrucu5/GFmWLGafoM+XMfnuQYA3GOYAc7GX2t5pg/FOzC3gUyUtIgZgbwCOE9wt+ynZL2N+CGwDVWNfKDgR8TPE0+BHbLptd9l+UebrFifli7rd+ZBtmTLnT3sSef1DZ1DfeBvCNYKcpctADeAxmJdw1ojCdyUmYI8ETQWdaZgnFz8NTEJaJnS38RGCCzI4QngCuN3oPGLS3YINmIPAY6p4dW2nR/T5BFmaYEJ0fMONvql4zGMleElG9xKpoloxHXq/zE8Rm2RTlJ+0whXADOGLZN8e0JGZeAyyXwtNNtpSWXR3d+BZS58AfRZ5CmhBW/Gwn+dC5oFBYJzsW4hLknHgUUaNcuUxEl8CjcS8YNGE+YnhIKx6xAbEWqxOy92271YWNhOYa3Qe8oHdOa00ugo8ETwjucSmfJXtvuevRATakHmjcuER8CXAo0IrLd9pMTHNAeMdZ/b5SNeBXzA+BXSl8BmgGywWg28CLrdcQ5ygTpF5FfgWcCymYFgkm24VBgaBuayCYq5QMFxLPOzzgPDxgom7FhIA1gTkVuT7ZNbJqpUZZemV+BkWW4xG1GjX5wzwUeKuZRHwK7m4AkJJciUlC2cNXfwtKmuG4CyrFWGQxQ9A01PUHgyWnwNmkBW3iNxFiHnAO4BnDF+weDTYpxrdI2l3otwAvlyZfmC5DejYMmV2Sa6rZAHVrcd/is2TZyNCKzHx/h4n23X8acJc19y5rSk4917ElZZGWqq29AHg89g1mf0L4Hrbbe5Zt8sIpuazYnOwS0Ze6Xxgb3cYSRsGqpbZbvxiMr2HZcYOq6iZm4lWxSPBu60bRsscjjRL+H6jRzGnG/+VYIyhtisXqoDuUl5PyQmM/PmXVUVmduXUnMmvWPylrMuQPhLMf2bmegfalA6fJ6WtC6jG8WjvTMFD4PkZuirAu0JGy+uD8zvq2kt7YL9fE+v1j89HUGvl5gOngZC9ETjN4iuYUxX3txn4opBRZ3GtJWS3gc8HLVRmNpcgfN+vPvCN7TlHkdBqcynmRswGYChoEuZWYEfycqttL7c8Hdgk+zHDBbYfNlm/kdfvCuxBXePt2OSDwmFBHmb0SmZvVdD3ZH8UuLCQdf44r8qxkoKhacvk17eOXDacl6ed269j328OF/XGkCfuoqqQYTwSdDhoJdCx5ehZ++NwyyijjDLeDETMR4SBdFGlLHc9ADiemHvoYt/uGMTuYp2uUhJYSjUcSTw7PZndBTJD9oEAKohhsJOIZWAlXVmUUoHF9NtCTBAdQywgXJceYffp+j/M3fZ+XUmMvwwmVjyNBjYnBY4AXiMmvkqCUu6FXyeG8zNiJVEtuyvVj04m/WR6HEfMM28iFhv2EPKbRFpPuWwluxPwTxL3ziUtpCl1yX9PadZ2oCldrIg1docCTxBDXYOSml4mFlaPT2S/lFzBOGBtckHd6fmORGw2kAmkl6l2EGtIisDvgVeI9b8NxMrKDcQCncHp/UIyzywpsZ1Y//Yab8P/mfB/oadUS+l51R+07ZfbzzLKKKOMMsooo4wyyiijjDLKeLvgvwF0O5R7wXjVRgAAAB50RVh0aWNjOmNvcHlyaWdodABHb29nbGUgSW5jLiAyMDE2rAszOAAAABR0RVh0aWNjOmRlc2NyaXB0aW9uAHNSR0K6kHMHAAAAAElFTkSuQmCC"

# ==================== ENDPOINTS ====================
@app.route('/')
def home():
    return f'''<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Taiyari - Assistant Marakame</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px; }}
        .chat-container {{ background: white; border-radius: 20px; box-shadow: 0 10px 40px rgba(0,0,0,0.3); width: 100%; max-width: 420px; overflow: hidden; }}
        .chat-header {{ background: white; padding: 16px 20px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #eee; }}
        .logo {{ width: 50px; height: 50px; }}
        .logo img {{ width: 100%; height: 100%; object-fit: contain; }}
        .header-text h1 {{ font-size: 1.1rem; font-weight: 600; color: #1a1a2e; }}
        .header-text p {{ font-size: 0.75rem; color: #666; margin-top: 2px; }}
        .chat-messages {{ height: 420px; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px; background: #f8f9fa; }}
        .message {{ max-width: 85%; padding: 12px 16px; border-radius: 18px; line-height: 1.5; font-size: 0.95rem; animation: fadeIn 0.3s ease; }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        .message.user {{ background: linear-gradient(135deg, #2d8f7b 0%, #20b2aa 100%); color: white; align-self: flex-end; border-bottom-right-radius: 4px; }}
        .message.bot {{ background: white; color: #333; align-self: flex-start; border-bottom-left-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); display: flex; gap: 10px; align-items: flex-start; }}
        .bot-avatar {{ width: 28px; height: 28px; flex-shrink: 0; }}
        .bot-avatar img {{ width: 100%; height: 100%; object-fit: contain; }}
        .message.error {{ background: #fee2e2; color: #dc2626; }}
        .loading-dots {{ display: flex; gap: 4px; padding: 4px 0; }}
        .loading-dots span {{ width: 8px; height: 8px; background: #2d8f7b; border-radius: 50%; animation: bounce 1.4s ease-in-out infinite; }}
        .loading-dots span:nth-child(2) {{ animation-delay: 0.2s; }}
        .loading-dots span:nth-child(3) {{ animation-delay: 0.4s; }}
        @keyframes bounce {{ 0%, 80%, 100% {{ transform: scale(0.6); opacity: 0.5; }} 40% {{ transform: scale(1); opacity: 1; }} }}
        .chat-input {{ display: flex; padding: 16px; border-top: 1px solid #eee; gap: 10px; background: white; }}
        .chat-input input {{ flex: 1; padding: 12px 18px; border: 2px solid #e5e7eb; border-radius: 25px; font-size: 0.95rem; outline: none; transition: border-color 0.2s; }}
        .chat-input input:focus {{ border-color: #2d8f7b; }}
        .chat-input button {{ background: linear-gradient(135deg, #2d8f7b 0%, #20b2aa 100%); color: white; border: none; width: 48px; height: 48px; border-radius: 50%; font-size: 1.2rem; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; display: flex; align-items: center; justify-content: center; }}
        .chat-input button:hover {{ transform: scale(1.05); box-shadow: 0 4px 15px rgba(45, 143, 123, 0.4); }}
        .chat-input button:disabled {{ background: #ccc; cursor: not-allowed; transform: none; box-shadow: none; }}
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">
            <div class="logo"><img src="data:image/png;base64,{LOGO_BASE64}" alt="Marakame"></div>
            <div class="header-text">
                <h1>Taiyari</h1>
                <p>Assistant Marakame</p>
            </div>
        </div>
        <div class="chat-messages" id="messages">
            <div class="message bot">
                <div class="bot-avatar"><img src="data:image/png;base64,{LOGO_BASE64}" alt="T"></div>
                <div>Bonjour ! 👋 Je suis Taiyari, votre assistant Marakame. Comment puis-je vous aider ?</div>
            </div>
        </div>
        <div class="chat-input">
            <input type="text" id="input" placeholder="Écrivez votre message..." onkeypress="if(event.key==='Enter')sendMessage()">
            <button onclick="sendMessage()">➤</button>
        </div>
    </div>
    <script>
        const LOGO = "data:image/png;base64,{LOGO_BASE64}";
        async function sendMessage() {{
            const input = document.getElementById('input');
            const messages = document.getElementById('messages');
            const message = input.value.trim();
            if (!message) return;
            messages.innerHTML += '<div class="message user">' + escapeHtml(message) + '</div>';
            input.value = '';
            const loadingId = Date.now();
            messages.innerHTML += '<div class="message bot" id="loading-' + loadingId + '"><div class="bot-avatar"><img src="' + LOGO + '" alt="T"></div><div class="loading-dots"><span></span><span></span><span></span></div></div>';
            messages.scrollTop = messages.scrollHeight;
            try {{
                const response = await fetch('/chat', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify({{ message }}) }});
                const data = await response.json();
                document.getElementById('loading-' + loadingId).remove();
                if (data.error) {{
                    messages.innerHTML += '<div class="message error">Erreur: ' + escapeHtml(data.error) + '</div>';
                }} else {{
                    messages.innerHTML += '<div class="message bot"><div class="bot-avatar"><img src="' + LOGO + '" alt="T"></div><div>' + escapeHtml(data.response) + '</div></div>';
                }}
            }} catch (error) {{
                document.getElementById('loading-' + loadingId).remove();
                messages.innerHTML += '<div class="message error">Erreur de connexion.</div>';
            }}
            messages.scrollTop = messages.scrollHeight;
        }}
        function escapeHtml(text) {{ const div = document.createElement('div'); div.textContent = text; return div.innerHTML; }}
    </script>
</body>
</html>'''

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'service': 'Taiyari'})

@app.route('/conversations')
def get_conversations():
    return jsonify({'total': len(conversations), 'conversations': conversations[-100:]})

@app.route('/chat', methods=['POST'])
def chat():
    if not ANTHROPIC_KEY:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured'}), 500
    
    data = request.json
    user_message = data.get('message', '')
    language = detect_language(user_message)
    
    # Chercher commande Shopify
    order_info = None
    for pattern in [r'#?\d{4,}', r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', r'MK-?\d+']:
        match = re.search(pattern, user_message)
        if match:
            order_info = get_shopify_order(match.group())
            break
    
    # RAG search
    context_docs = rag.search(user_message, language=language, top_k=3)
    context = "\n".join([doc['content'] for doc in context_docs])
    
    if order_info:
        formatted = format_order_info(order_info, language)
        if formatted:
            context += f"\n\nCOMMANDE: {formatted['order_number']} - Statut: {formatted['status']} - Total: {formatted['total']} - Date: {formatted['created_at']}"
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=get_taiyari_prompt(language, context),
        messages=[{"role": "user", "content": user_message}]
    )
    
    bot_response = response.content[0].text
    log_conversation(user_message, bot_response, language)
    
    return jsonify({'response': bot_response, 'language': language})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

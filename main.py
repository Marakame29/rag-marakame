from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
import requests
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import uuid
import threading
import json
from urllib.parse import urljoin, urlparse

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'marakame-taiyari-secret-2024')
CORS(app, supports_credentials=True)

# ==================== CONFIGURATION ====================
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY')
SHOPIFY_CLIENT_ID = os.environ.get('SHOPIFY_CLIENT_ID')
SHOPIFY_CLIENT_SECRET = os.environ.get('SHOPIFY_CLIENT_SECRET')
SHOPIFY_SHOP_URL = os.environ.get('SHOPIFY_SHOP_URL', '792489-4.myshopify.com')
HUBSPOT_API_KEY = os.environ.get('HUBSPOT_API_KEY')

# SMTP Config
SMTP_HOST = os.environ.get('SMTP_HOST', 'mail.privateemail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER', 'hello@marakame.ch')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
SMTP_FROM = os.environ.get('SMTP_FROM', 'info@marakame.ch')

# Website to scrape
WEBSITE_URL = 'https://marakame.ch'

# Session timeout settings
TIMEOUT_WARNING = 5 * 60
TIMEOUT_CLOSE = 10 * 60

# Session limits (anti-abuse)
MAX_MESSAGES_PER_SESSION = 20
MAX_SESSION_DURATION = 15 * 60  # 15 minutes

# ==================== LANGUAGE DETECTION & TRANSLATION ====================
def detect_language(text):
    """Detect language of the text"""
    text_lower = text.lower()
    
    # Spanish indicators
    es_words = ['hola', 'gracias', 'por favor', 'qué', 'cuál', 'cómo', 'dónde', 'cuándo', 'tiempo', 'entrega', 
                'pedido', 'envío', 'precio', 'quiero', 'puedo', 'necesito', 'tengo', 'está', 'son', 'tienen',
                'buenas', 'buenos', 'días', 'tardes', 'noches', 'el', 'la', 'los', 'las', 'de', 'del']
    es_count = sum(1 for w in es_words if w in text_lower)
    
    # English indicators
    en_words = ['hello', 'hi', 'thanks', 'please', 'what', 'which', 'how', 'where', 'when', 'delivery', 
                'order', 'shipping', 'price', 'want', 'can', 'need', 'have', 'is', 'are', 'the', 'a', 'an',
                'good', 'morning', 'afternoon', 'evening', 'my', 'your', 'do', 'does']
    en_count = sum(1 for w in en_words if w in text_lower)
    
    # German indicators
    de_words = ['hallo', 'danke', 'bitte', 'was', 'wie', 'wo', 'wann', 'lieferung', 'bestellung', 'versand',
                'preis', 'ich', 'möchte', 'kann', 'brauche', 'habe', 'ist', 'sind', 'der', 'die', 'das',
                'guten', 'morgen', 'tag', 'abend', 'mein', 'ihr']
    de_count = sum(1 for w in de_words if w in text_lower)
    
    # Italian indicators
    it_words = ['ciao', 'grazie', 'per favore', 'cosa', 'quale', 'come', 'dove', 'quando', 'consegna',
                'ordine', 'spedizione', 'prezzo', 'voglio', 'posso', 'ho bisogno', 'ho', 'è', 'sono',
                'buongiorno', 'buonasera', 'il', 'la', 'i', 'le', 'di', 'del']
    it_count = sum(1 for w in it_words if w in text_lower)
    
    # Arabic indicators (transliterated common words)
    ar_indicators = ['مرحبا', 'شكرا', 'من فضلك', 'ماذا', 'كيف', 'أين', 'متى', 'التسليم', 'الطلب']
    ar_count = sum(1 for w in ar_indicators if w in text)
    
    # Find highest score
    scores = {'es': es_count, 'en': en_count, 'de': de_count, 'it': it_count, 'ar': ar_count}
    max_lang = max(scores, key=scores.get)
    max_score = scores[max_lang]
    
    # Return detected language if score > 1, else default to French
    if max_score > 1:
        return max_lang
    return 'fr'

def translate_to_french_for_rag(text, source_lang):
    """Translate common e-commerce terms to French for better RAG matching"""
    translations = {
        'es': {
            'tiempo de entrega': 'délai de livraison',
            'entrega': 'livraison',
            'envío': 'livraison expédition',
            'envio': 'livraison expédition',
            'precio': 'prix',
            'pedido': 'commande',
            'pulsera': 'bracelet',
            'pulseras': 'bracelets',
            'collar': 'collier',
            'collares': 'colliers',
            'anillo': 'bague',
            'anillos': 'bagues',
            'pendientes': 'boucles oreilles',
            'aretes': 'boucles oreilles',
            'joyería': 'bijoux',
            'artesanal': 'artisanal',
            'hecho a mano': 'fait main',
            'cuánto': 'combien',
            'cómo': 'comment',
            'dónde': 'où',
            'cuándo': 'quand',
            'qué': 'quoi',
            'comprar': 'acheter',
            'devolver': 'retourner',
            'devolución': 'retour',
            'pago': 'paiement',
            'tarjeta': 'carte',
            'suiza': 'suisse',
            'españa': 'espagne europe international',
            'spain': 'espagne europe international',
            'mexico': 'mexique international',
            'méxico': 'mexique international',
            'estados unidos': 'usa international',
            'francia': 'france europe',
            'alemania': 'allemagne europe',
            'italia': 'italie europe',
            'internacional': 'international',
            'gratis': 'gratuit',
            'gratuito': 'gratuit',
            'hacen': 'font faire',
            'entregas': 'livraisons livraison'
        },
        'en': {
            'delivery time': 'délai de livraison',
            'delivery': 'livraison',
            'shipping': 'livraison expédition',
            'price': 'prix',
            'order': 'commande',
            'bracelet': 'bracelet',
            'bracelets': 'bracelets',
            'necklace': 'collier',
            'necklaces': 'colliers',
            'ring': 'bague',
            'rings': 'bagues',
            'earrings': 'boucles oreilles',
            'jewelry': 'bijoux',
            'handmade': 'fait main',
            'artisan': 'artisanal',
            'how much': 'combien',
            'how': 'comment',
            'where': 'où',
            'when': 'quand',
            'what': 'quoi',
            'buy': 'acheter',
            'return': 'retour',
            'payment': 'paiement',
            'card': 'carte',
            'switzerland': 'suisse',
            'international': 'international',
            'free': 'gratuit'
        },
        'de': {
            'lieferzeit': 'délai de livraison',
            'lieferung': 'livraison',
            'versand': 'livraison expédition',
            'preis': 'prix',
            'bestellung': 'commande',
            'armband': 'bracelet',
            'armbänder': 'bracelets',
            'halskette': 'collier',
            'kette': 'collier',
            'ring': 'bague',
            'ohrringe': 'boucles oreilles',
            'schmuck': 'bijoux',
            'handgemacht': 'fait main',
            'wie viel': 'combien',
            'wie': 'comment',
            'wo': 'où',
            'wann': 'quand',
            'was': 'quoi',
            'kaufen': 'acheter',
            'rückgabe': 'retour',
            'zahlung': 'paiement',
            'karte': 'carte',
            'schweiz': 'suisse',
            'international': 'international',
            'kostenlos': 'gratuit'
        },
        'it': {
            'tempo di consegna': 'délai de livraison',
            'consegna': 'livraison',
            'spedizione': 'livraison expédition',
            'prezzo': 'prix',
            'ordine': 'commande',
            'bracciale': 'bracelet',
            'bracciali': 'bracelets',
            'collana': 'collier',
            'collane': 'colliers',
            'anello': 'bague',
            'anelli': 'bagues',
            'orecchini': 'boucles oreilles',
            'gioielli': 'bijoux',
            'fatto a mano': 'fait main',
            'artigianale': 'artisanal',
            'quanto': 'combien',
            'come': 'comment',
            'dove': 'où',
            'quando': 'quand',
            'cosa': 'quoi',
            'comprare': 'acheter',
            'reso': 'retour',
            'pagamento': 'paiement',
            'carta': 'carte',
            'svizzera': 'suisse',
            'internazionale': 'international',
            'gratuito': 'gratuit'
        }
    }
    
    if source_lang not in translations:
        return text
    
    translated = text.lower()
    for source_term, french_term in translations[source_lang].items():
        translated = translated.replace(source_term, french_term)
    
    # Also keep original text for combined search
    return f"{translated} {text}"

# ==================== DYNAMIC RAG ====================
class DynamicRAG:
    def __init__(self):
        self.documents = []
        self.index = defaultdict(list)
        self.last_update = None
        self.update_interval = 3600  # 1 hour
        self.is_updating = False
    
    def needs_update(self):
        if self.last_update is None:
            return True
        return (datetime.now() - self.last_update).total_seconds() > self.update_interval
    
    def _tokenize(self, text):
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        return [w for w in text.split() if len(w) > 2]
    
    def _extract_text_from_html(self, html):
        """Extract clean text from HTML"""
        # Remove script and style elements
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', html)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove common navigation text
        noise_patterns = [
            r'Ignorer et passer au contenu',
            r'Livraison gratuite.*?CHF \d+',
            r'Pays/région.*?Langue',
            r'Rechercher.*?Connexion',
            r'Article ajouté au panier',
            r'Procéder au paiement',
            r'Continuer les achats',
            r'© \d{4}.*?Shopify',
            r'Moyens de paiement.*?Visa',
        ]
        for pattern in noise_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)
        return text.strip()
    
    def _get_page_title(self, html):
        """Extract page title"""
        match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if match:
            title = match.group(1).split('–')[0].split('|')[0].strip()
            return title
        return ""
    
    def scrape_website(self):
        """Scrape all pages from marakame.ch"""
        print("DEBUG RAG: Starting website scrape...")
        documents = []
        visited = set()
        to_visit = [WEBSITE_URL]
        
        # Key pages to definitely scrape
        key_pages = [
            '/pages/faq',
            '/pages/histoire',
            '/pages/ou-nous-trouver',
            '/collections/artisanat-wayuu',
            '/collections/boucles-doreilles',
            '/collections/bagues-ajustables',
            '/collections/mexique',
            '/collections/colombie',
            '/policies/refund-policy',
            '/policies/shipping-policy',
        ]
        for page in key_pages:
            to_visit.append(urljoin(WEBSITE_URL, page))
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; TaiyariBot/1.0; +https://marakame.ch)'
        }
        
        while to_visit and len(visited) < 50:  # Limit to 50 pages
            url = to_visit.pop(0)
            
            # Normalize URL
            parsed = urlparse(url)
            if parsed.netloc and 'marakame.ch' not in parsed.netloc:
                continue
            url = url.split('?')[0].split('#')[0]
            
            if url in visited:
                continue
            
            # Skip certain URLs
            skip_patterns = ['/account', '/cart', '/checkout', '/cdn/', '.jpg', '.png', '.gif', '.css', '.js']
            if any(p in url.lower() for p in skip_patterns):
                continue
            
            visited.add(url)
            
            try:
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code != 200:
                    continue
                
                html = response.text
                title = self._get_page_title(html)
                content = self._extract_text_from_html(html)
                
                if len(content) > 100:  # Only add pages with substantial content
                    # Determine category
                    category = 'general'
                    if '/faq' in url:
                        category = 'faq'
                    elif '/collections/' in url or '/products/' in url:
                        category = 'produits'
                    elif '/histoire' in url:
                        category = 'histoire'
                    elif '/policies/' in url:
                        category = 'politique'
                    
                    documents.append({
                        'content': content[:3000],  # Limit content size
                        'url': url,
                        'title': title,
                        'category': category,
                        'source': 'website'
                    })
                    print(f"DEBUG RAG: Scraped {url} ({len(content)} chars)")
                
                # Find more links
                links = re.findall(r'href=["\']([^"\']+)["\']', html)
                for link in links:
                    full_url = urljoin(url, link)
                    if 'marakame.ch' in full_url and full_url not in visited:
                        to_visit.append(full_url)
                
            except Exception as e:
                print(f"DEBUG RAG: Error scraping {url}: {e}")
        
        print(f"DEBUG RAG: Website scrape complete. {len(documents)} pages scraped.")
        return documents
    
    def scrape_shopify_products(self):
        """Scrape products from Shopify"""
        print("DEBUG RAG: Starting Shopify scrape...")
        documents = []
        
        token = get_shopify_token()
        if not token:
            print("DEBUG RAG: No Shopify token available")
            return documents
        
        headers = {
            'X-Shopify-Access-Token': token,
            'Content-Type': 'application/json'
        }
        
        try:
            # Get all products
            url = f'https://{SHOPIFY_SHOP_URL}/admin/api/2024-01/products.json?limit=250'
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                products = response.json().get('products', [])
                print(f"DEBUG RAG: Found {len(products)} Shopify products")
                
                for product in products:
                    title = product.get('title', '')
                    description = product.get('body_html', '')
                    # Clean HTML from description
                    description = re.sub(r'<[^>]+>', ' ', description)
                    description = re.sub(r'\s+', ' ', description).strip()
                    
                    product_type = product.get('product_type', '')
                    vendor = product.get('vendor', '')
                    tags = ', '.join(product.get('tags', []))
                    
                    # Get price from first variant
                    variants = product.get('variants', [])
                    price = variants[0].get('price', '') if variants else ''
                    
                    # Get product URL
                    handle = product.get('handle', '')
                    product_url = f"https://marakame.ch/products/{handle}"
                    
                    content = f"""Produit: {title}
Description: {description}
Type: {product_type}
Prix: {price} CHF
Tags: {tags}
Disponible sur: {product_url}"""
                    
                    documents.append({
                        'content': content,
                        'url': product_url,
                        'title': title,
                        'category': 'produit',
                        'source': 'shopify',
                        'price': price
                    })
            else:
                print(f"DEBUG RAG: Shopify API error: {response.status_code}")
        
        except Exception as e:
            print(f"DEBUG RAG: Shopify scrape error: {e}")
        
        print(f"DEBUG RAG: Shopify scrape complete. {len(documents)} products.")
        return documents
    
    def add_documents(self, docs):
        """Add documents to the index"""
        for doc in docs:
            doc_id = len(self.documents)
            self.documents.append(doc)
            
            # Index by words
            words = self._tokenize(doc['content'])
            for word in set(words):
                self.index[word].append(doc_id)
            
            # Index by title words
            if doc.get('title'):
                for word in self._tokenize(doc['title']):
                    self.index[word].append(doc_id)
    
    def update(self):
        """Update the RAG with fresh data"""
        if self.is_updating:
            print("DEBUG RAG: Update already in progress")
            return
        
        self.is_updating = True
        print("DEBUG RAG: Starting full RAG update...")
        
        try:
            # Clear existing data
            self.documents = []
            self.index = defaultdict(list)
            
            # Add static FAQ first (most important info)
            static_faq = self.get_static_faq()
            self.add_documents(static_faq)
            
            # Scrape website
            website_docs = self.scrape_website()
            self.add_documents(website_docs)
            
            # Scrape Shopify
            shopify_docs = self.scrape_shopify_products()
            self.add_documents(shopify_docs)
            
            self.last_update = datetime.now()
            print(f"DEBUG RAG: Update complete. Total documents: {len(self.documents)}")
        
        except Exception as e:
            print(f"DEBUG RAG: Update error: {e}")
        
        finally:
            self.is_updating = False
    
    def get_static_faq(self):
        """Static FAQ with essential information that must always be available"""
        return [
            {
                'content': """DÉLAIS DE LIVRAISON / DELIVERY TIME / TIEMPO DE ENTREGA / LIEFERZEIT:

SUISSE (Switzerland/Suiza/Schweiz):
- Délai: 1-3 jours ouvrables
- Frais: CHF 7.90 (GRATUIT dès CHF 80 d'achat)

FRANCE:
- Délai: 5-10 jours ouvrables
- Livraison internationale standard

EUROPE (Allemagne, Espagne, Italie, Belgique, Pays-Bas, Autriche, Portugal, etc.):
- Délai: 5-10 jours ouvrables
- Livraison internationale standard
- Inclut: Germany/Deutschland, Spain/España, Italy/Italia, Belgium/Belgique, Netherlands, Austria/Österreich, Portugal, etc.

INTERNATIONAL (USA, Canada, Mexique, Amérique latine, Asie, Afrique, Océanie, tous autres pays):
- Délai: 10-15 jours ouvrables
- Livraison internationale
- Inclut: United States, Mexico/México, Brazil/Brasil, Argentina, Colombia, Chile, Japon, Chine, Australie, etc.

IMPORTANT: Toutes les commandes sont expédiées sous 24-48h après validation du paiement.
Nous livrons dans le monde entier / We ship worldwide / Enviamos a todo el mundo / Wir liefern weltweit.""",
                'source': 'faq',
                'url': 'https://marakame.ch/pages/faq'
            },
            {
                'content': """MÉTHODES DE PAIEMENT / PAYMENT METHODS / MÉTODOS DE PAGO / ZAHLUNGSMETHODEN:
- Carte de crédit (Visa, Mastercard, American Express)
- PayPal
- TWINT (Suisse uniquement / Switzerland only / Solo Suiza)
- Virement bancaire / Bank transfer / Transferencia bancaria
Toutes les transactions sont sécurisées et cryptées.
All transactions are secure and encrypted.
Todas las transacciones son seguras y encriptadas.""",
                'source': 'faq',
                'url': 'https://marakame.ch/pages/faq'
            },
            {
                'content': """RETOURS ET ÉCHANGES / RETURNS & EXCHANGES / DEVOLUCIONES Y CAMBIOS / RÜCKGABE:
- Retour gratuit sous 14 jours / Free returns within 14 days / Devolución gratuita en 14 días
- Article non porté, dans son emballage d'origine
- Remboursement sous 5-7 jours ouvrables après réception
- Pour initier un retour, contactez info@marakame.ch
- To initiate a return, contact info@marakame.ch
- Para iniciar una devolución, contacte info@marakame.ch""",
                'source': 'faq',
                'url': 'https://marakame.ch/pages/faq'
            },
            {
                'content': """À PROPOS DE MARAKAME / ABOUT MARAKAME / SOBRE MARAKAME / ÜBER MARAKAME:
Marakame est une boutique suisse spécialisée dans les bijoux et accessoires artisanaux faits main.
Marakame is a Swiss boutique specializing in handmade artisan jewelry and accessories.
Marakame es una boutique suiza especializada en joyería y accesorios artesanales hechos a mano.
Nos bracelets sont créés par des artisans au Mexique, utilisant des techniques traditionnelles transmises de génération en génération.
Chaque pièce est unique et fabriquée avec amour et savoir-faire.""",
                'source': 'faq',
                'url': 'https://marakame.ch/pages/about'
            },
            {
                'content': """CONTACT:
- Email: info@marakame.ch
- Site web / Website / Sitio web: https://marakame.ch
- Basé en Suisse / Based in Switzerland / Con sede en Suiza
Pour toute question sur une commande, veuillez fournir votre numéro de commande ou l'email utilisé lors de l'achat.
For any order questions, please provide your order number or the email used during purchase.
Para cualquier pregunta sobre un pedido, proporcione su número de pedido o el email utilizado en la compra.""",
                'source': 'faq',
                'url': 'https://marakame.ch/pages/contact'
            },
            {
                'content': """SUIVI DE COMMANDE / ORDER TRACKING / SEGUIMIENTO DE PEDIDO / SENDUNGSVERFOLGUNG:
Une fois votre commande expédiée, vous recevrez un email avec le numéro de suivi.
Once your order is shipped, you will receive an email with the tracking number.
Una vez enviado su pedido, recibirá un email con el número de seguimiento.
Vous pouvez suivre votre colis via le lien fourni dans l'email de confirmation d'expédition.
Pour toute question sur votre commande, contactez-nous avec votre numéro de commande.""",
                'source': 'faq',
                'url': 'https://marakame.ch/pages/faq'
            }
        ]
    
    def search(self, query, top_k=5):
        """Search the RAG"""
        # Check if update needed
        if self.needs_update():
            # Run update in background
            threading.Thread(target=self.update).start()
            # If no documents yet, wait a bit for initial load
            if not self.documents:
                time.sleep(2)
        
        if not self.documents:
            return []
        
        query_words = self._tokenize(query)
        scores = defaultdict(float)
        
        for word in query_words:
            if word in self.index:
                for doc_id in self.index[word]:
                    scores[doc_id] += 1
        
        # Boost scores for certain categories based on query
        query_lower = query.lower()
        for doc_id, score in list(scores.items()):
            doc = self.documents[doc_id]
            # Boost product results for product-related queries
            if any(w in query_lower for w in ['prix', 'price', 'coût', 'combien', 'acheter', 'buy']):
                if doc.get('source') == 'shopify':
                    scores[doc_id] *= 1.5
            # Boost FAQ for question words
            if any(w in query_lower for w in ['comment', 'pourquoi', 'quand', 'how', 'why', 'when']):
                if doc.get('category') == 'faq':
                    scores[doc_id] *= 1.3
        
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        results = []
        
        for doc_id, score in ranked[:top_k]:
            doc = self.documents[doc_id]
            results.append({
                'content': doc['content'],
                'url': doc.get('url', ''),
                'title': doc.get('title', ''),
                'category': doc.get('category', ''),
                'source': doc.get('source', ''),
                'score': score
            })
        
        return results

# Initialize RAG
rag = DynamicRAG()

# ==================== SESSION STORAGE ====================
sessions = {}

def get_session(session_id):
    if session_id not in sessions:
        sessions[session_id] = {
            'id': session_id,
            'started_at': datetime.now().isoformat(),
            'session_start': datetime.now(),
            'last_activity': datetime.now(),
            'messages': [],
            'message_count': 0,
            'visitor_email': None,
            'greeted': False,
            'warning_sent': False,
            'closed': False,
            'close_reason': None
        }
    return sessions[session_id]

def update_session_activity(session_id):
    if session_id in sessions:
        sessions[session_id]['last_activity'] = datetime.now()
        sessions[session_id]['warning_sent'] = False

def check_session_limits(session_id):
    """Check if session has reached message or time limits"""
    if session_id not in sessions:
        return None
    
    session_data = sessions[session_id]
    
    if session_data['closed']:
        return {
            'limited': True,
            'reason': session_data.get('close_reason', 'closed'),
            'message': "Cette conversation est terminée. Actualisez la page pour démarrer une nouvelle conversation. 🔄"
        }
    
    # Check message limit
    if session_data['message_count'] >= MAX_MESSAGES_PER_SESSION:
        session_data['closed'] = True
        session_data['close_reason'] = 'message_limit'
        threading.Thread(target=send_conversation_copy, args=(session_id,)).start()
        return {
            'limited': True,
            'reason': 'message_limit',
            'message': f"Nous avons atteint la limite de {MAX_MESSAGES_PER_SESSION} messages pour cette conversation. 📝 Pour continuer, actualisez la page pour démarrer une nouvelle session. Merci de votre compréhension !"
        }
    
    # Check time limit
    session_duration = (datetime.now() - session_data['session_start']).total_seconds()
    if session_duration >= MAX_SESSION_DURATION:
        session_data['closed'] = True
        session_data['close_reason'] = 'time_limit'
        threading.Thread(target=send_conversation_copy, args=(session_id,)).start()
        return {
            'limited': True,
            'reason': 'time_limit',
            'message': "Notre conversation dure depuis 15 minutes. ⏰ Pour continuer, actualisez la page pour démarrer une nouvelle session. Merci pour cet échange !"
        }
    
    # Warning at 80% of limits
    messages_remaining = MAX_MESSAGES_PER_SESSION - session_data['message_count']
    time_remaining = MAX_SESSION_DURATION - session_duration
    
    warning = None
    if messages_remaining == 3:
        warning = f"⚠️ Il vous reste {messages_remaining} messages dans cette session."
    elif time_remaining <= 120 and time_remaining > 60:  # 2 minutes left
        warning = "⚠️ Il reste environ 2 minutes à cette session."
    
    return {'limited': False, 'warning': warning}

def check_session_timeout(session_id):
    if session_id not in sessions:
        return None
    
    session_data = sessions[session_id]
    if session_data['closed']:
        return None
    
    elapsed = (datetime.now() - session_data['last_activity']).total_seconds()
    
    if elapsed >= TIMEOUT_CLOSE:
        session_data['closed'] = True
        threading.Thread(target=send_conversation_copy, args=(session_id,)).start()
        return {
            'type': 'closed',
            'message': "Il semble que vous ne soyez plus connecté. Je ferme cette conversation. Une copie a été envoyée à notre équipe. N'hésitez pas à revenir si vous avez d'autres questions ! 👋"
        }
    elif elapsed >= TIMEOUT_WARNING and not session_data['warning_sent']:
        session_data['warning_sent'] = True
        return {
            'type': 'warning',
            'message': "Êtes-vous toujours là ? 🙂"
        }
    
    return None

# ==================== EMAIL FUNCTIONS ====================
def send_email(to_email, subject, body_html):
    """Send email via SMTP Namecheap - using SSL on port 465"""
    print(f"DEBUG EMAIL: === Starting send_email ===")
    print(f"DEBUG EMAIL: To: {to_email}")
    print(f"DEBUG EMAIL: SMTP_HOST: {SMTP_HOST}")
    print(f"DEBUG EMAIL: SMTP_PORT: {SMTP_PORT}")
    print(f"DEBUG EMAIL: SMTP_USER: {SMTP_USER}")
    print(f"DEBUG EMAIL: SMTP_PASSWORD set: {bool(SMTP_PASSWORD)}")
    print(f"DEBUG EMAIL: SMTP_FROM: {SMTP_FROM}")
    
    if not SMTP_PASSWORD:
        print("DEBUG EMAIL: ERROR - SMTP_PASSWORD is not configured!")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"Marakame <{SMTP_FROM}>"
        msg['To'] = to_email
        
        html_part = MIMEText(body_html, 'html', 'utf-8')
        msg.attach(html_part)
        
        # Try SSL first (port 465), then TLS (port 587)
        port = int(SMTP_PORT)
        
        if port == 465:
            print(f"DEBUG EMAIL: Using SMTP_SSL on port 465...")
            import ssl
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=30, context=context)
        else:
            print(f"DEBUG EMAIL: Using SMTP with STARTTLS on port {port}...")
            server = smtplib.SMTP(SMTP_HOST, port, timeout=30)
            server.starttls()
        
        print(f"DEBUG EMAIL: Connected! Logging in as {SMTP_USER}...")
        server.login(SMTP_USER, SMTP_PASSWORD)
        print("DEBUG EMAIL: Login OK!")
        
        print(f"DEBUG EMAIL: Sending email...")
        server.sendmail(SMTP_FROM, to_email, msg.as_string())
        print("DEBUG EMAIL: Send OK!")
        
        server.quit()
        print(f"DEBUG EMAIL: === SUCCESS - Email sent to {to_email} ===")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"DEBUG EMAIL: AUTHENTICATION ERROR - Wrong username/password: {e}")
        return False
    except smtplib.SMTPConnectError as e:
        print(f"DEBUG EMAIL: CONNECTION ERROR - Cannot connect to server: {e}")
        return False
    except smtplib.SMTPException as e:
        print(f"DEBUG EMAIL: SMTP ERROR: {e}")
        return False
    except TimeoutError as e:
        print(f"DEBUG EMAIL: TIMEOUT ERROR - Server not responding: {e}")
        return False
    except Exception as e:
        print(f"DEBUG EMAIL: GENERAL ERROR - {type(e).__name__}: {e}")
        return False

def format_conversation_html(session_data):
    """Format conversation as HTML for email"""
    messages_html = ""
    for msg in session_data['messages']:
        role = "Visiteur" if msg['role'] == 'user' else "Taiyari"
        color = "#2d8f7b" if msg['role'] == 'user' else "#666"
        messages_html += f"""
        <div style="margin-bottom: 10px;">
            <strong style="color: {color};">{role}:</strong>
            <p style="margin: 5px 0; padding: 10px; background: #f5f5f5; border-radius: 8px;">{msg['content']}</p>
            <small style="color: #999;">{msg['timestamp']}</small>
        </div>
        """
    
    visitor_email = session_data.get('visitor_email', 'Non fourni')
    
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #2d8f7b; color: white; padding: 20px; text-align: center;">
            <h1 style="margin: 0;">Conversation Taiyari</h1>
        </div>
        <div style="padding: 20px;">
            <p><strong>Date:</strong> {session_data['started_at']}</p>
            <p><strong>Email visiteur:</strong> {visitor_email}</p>
            <hr style="border: 1px solid #eee;">
            <h3>Conversation:</h3>
            {messages_html}
        </div>
        <div style="background: #f5f5f5; padding: 15px; text-align: center; color: #666;">
            <small>Marakame - Bijoux et accessoires artisanaux</small>
        </div>
    </body>
    </html>
    """

def send_conversation_copy(session_id):
    """Send conversation copy to info@marakame.ch and visitor"""
    print(f"DEBUG: send_conversation_copy called for session {session_id}")
    
    if session_id not in sessions:
        print(f"DEBUG: Session {session_id} not found")
        return
    
    session_data = sessions[session_id]
    if not session_data['messages']:
        print("DEBUG: No messages in session")
        return
    
    html_content = format_conversation_html(session_data)
    subject = f"Conversation Taiyari - {session_data['started_at'][:10]}"
    
    # Send to info@marakame.ch
    print("DEBUG: Sending to info@marakame.ch...")
    send_email('info@marakame.ch', subject, html_content)
    
    # Send to visitor if email provided
    if session_data.get('visitor_email'):
        print(f"DEBUG: Sending to visitor {session_data['visitor_email']}...")
        send_email(session_data['visitor_email'], "Copie de votre conversation avec Marakame", html_content)

# ==================== HUBSPOT FUNCTIONS ====================
def search_hubspot_contact(email):
    if not HUBSPOT_API_KEY:
        return None
    
    try:
        url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
        headers = {
            'Authorization': f'Bearer {HUBSPOT_API_KEY}',
            'Content-Type': 'application/json'
        }
        payload = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "email",
                    "operator": "EQ",
                    "value": email
                }]
            }],
            "properties": ["email", "firstname", "lastname"]
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('results'):
                return data['results'][0]
        return None
    except Exception as e:
        print(f"DEBUG: HubSpot contact error: {e}")
        return None

def get_hubspot_emails(email):
    """Get emails from HubSpot for a contact"""
    if not HUBSPOT_API_KEY:
        return []
    
    try:
        contact = search_hubspot_contact(email)
        if not contact:
            print(f"DEBUG: No HubSpot contact found for {email}")
            return []
        
        contact_id = contact['id']
        firstname = contact.get('properties', {}).get('firstname', '')
        
        url = f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}/associations/emails"
        headers = {
            'Authorization': f'Bearer {HUBSPOT_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return []
        
        associations = response.json().get('results', [])
        
        if not associations:
            return []
        
        emails = []
        for assoc in associations[:5]:
            email_id = assoc.get('id') or assoc.get('toObjectId')
            if not email_id:
                continue
            
            email_url = f"https://api.hubapi.com/crm/v3/objects/emails/{email_id}?properties=hs_email_subject,hs_email_text,hs_email_html,hs_body_preview,hs_timestamp,hs_email_direction"
            email_response = requests.get(email_url, headers=headers, timeout=10)
            
            if email_response.status_code == 200:
                email_data = email_response.json()
                props = email_data.get('properties', {})
                
                body = props.get('hs_email_text') or props.get('hs_body_preview') or props.get('hs_email_html') or ''
                
                if '<' in body and '>' in body:
                    body = re.sub(r'<[^>]+>', ' ', body)
                    body = re.sub(r'\s+', ' ', body).strip()
                
                emails.append({
                    'subject': props.get('hs_email_subject', 'Sans sujet'),
                    'body': body[:500] if body else '',
                    'date': props.get('hs_timestamp', ''),
                    'direction': props.get('hs_email_direction', ''),
                    'firstname': firstname
                })
        
        return emails
    except Exception as e:
        print(f"DEBUG: HubSpot emails error: {e}")
        return []

# ==================== SHOPIFY TOKEN ====================
shopify_token_cache = {'access_token': None, 'expires_at': 0}

def get_shopify_token():
    if shopify_token_cache['access_token'] and time.time() < shopify_token_cache['expires_at'] - 300:
        return shopify_token_cache['access_token']
    
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        return None
    
    try:
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
            return data['access_token']
    except Exception as e:
        print(f"DEBUG: Shopify token error: {e}")
    return None

def get_shopify_order(order_id_or_email):
    token = get_shopify_token()
    if not token:
        return None
    
    headers = {'X-Shopify-Access-Token': token, 'Content-Type': 'application/json'}
    
    try:
        if '@' in order_id_or_email:
            url = f'https://{SHOPIFY_SHOP_URL}/admin/api/2024-01/orders.json?email={order_id_or_email}&status=any'
        else:
            order_num = order_id_or_email.replace('#', '').replace('MK', '').strip()
            url = f'https://{SHOPIFY_SHOP_URL}/admin/api/2024-01/orders.json?name=%23{order_num}&status=any'
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('orders'):
                return data['orders'][0]
    except Exception as e:
        print(f"DEBUG: Shopify error: {e}")
    return None

def format_order_info(order):
    if not order:
        return None
    status_map = {'fulfilled': 'Expédiée', 'unfulfilled': 'En préparation', 'partially_fulfilled': 'Partiellement expédiée'}
    status = order.get('fulfillment_status') or 'unfulfilled'
    return {
        'order_number': order.get('name', ''),
        'status': status_map.get(status, status),
        'total': f"{order.get('total_price', '0')} {order.get('currency', 'CHF')}",
        'created_at': order.get('created_at', '')[:10]
    }

# ==================== TAIYARI PROMPT ====================
def get_taiyari_prompt(language, context, is_continuing=False, hubspot_email_content=None):
    continuation_rule = "NE PAS saluer à nouveau - la conversation est déjà en cours." if is_continuing else ""
    
    hubspot_instruction = ""
    if hubspot_email_content:
        hubspot_instruction = f"""
EMAIL DU CLIENT TROUVÉ DANS HUBSPOT:
{hubspot_email_content}

Tu dois RÉPONDRE à cette question en utilisant les informations du CONTEXTE ci-dessous."""

    # Instructions de langue
    language_instruction = f"""
LANGUE DE RÉPONSE: {language}
Tu dois TOUJOURS répondre dans la même langue que le message du visiteur.
- Si le visiteur écrit en français, réponds en français
- Si le visiteur écrit en espagnol, réponds en espagnol
- Si le visiteur écrit en anglais, réponds en anglais
- Si le visiteur écrit en allemand, réponds en allemand
- Si le visiteur écrit en italien, réponds en italien
- Etc. pour toutes les langues

Adapte tes expressions naturelles à la langue:
- Français: "Hmm...", "Voyons voir...", "Ah !"
- Espagnol: "Mmm...", "Veamos...", "¡Ah!"
- Anglais: "Hmm...", "Let me see...", "Ah!"
- Allemand: "Hmm...", "Mal sehen...", "Ah!"
"""

    return f"""Tu es Taiyari, l'assistant virtuel de Marakame, une boutique suisse de bijoux et accessoires artisanaux faits main.

{language_instruction}

PERSONNALITÉ:
- Chaleureux, amical et professionnel
- Expressions naturelles adaptées à la langue du visiteur
- Concis: 2-3 phrases max pour les réponses simples
- Emojis avec parcimonie (1-2 max)
- Vouvoie les clients (ou équivalent formel dans la langue)

RÈGLES STRICTES:
1. NE JAMAIS utiliser le mot "Huichol"
2. {continuation_rule}
3. TOUJOURS chercher la réponse dans le CONTEXTE avant de dire que tu ne sais pas
4. Si la question est GÉNÉRALE, donne un résumé court (2-3 lignes) + le lien vers la page
5. Si la question est PRÉCISE, réponds directement avec les détails
6. Ne rediriger vers info@marakame.ch QUE si la réponse n'est PAS dans le contexte
7. Pour les commandes, demande le numéro ou l'email si non fourni
8. Inclure les liens URL des sources quand pertinent
9. TOUJOURS répondre dans la MÊME LANGUE que le visiteur
{hubspot_instruction}

CONTEXTE (données du site, produits Shopify, FAQ):
{context}"""

# ==================== LOGO ====================
LOGO_BASE64 = "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"

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
        .bot-text a {{ color: #2d8f7b; }}
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
        .end-chat {{ background: #f0f0f0; border: none; padding: 8px 16px; border-radius: 20px; font-size: 0.8rem; cursor: pointer; margin: 10px auto; display: block; color: #666; }}
        .end-chat:hover {{ background: #e0e0e0; }}
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
                <div class="bot-text">Bonjour ! 👋 Je suis Taiyari, votre assistant Marakame. Comment puis-je vous aider ?</div>
            </div>
        </div>
        <div class="chat-input">
            <input type="text" id="input" placeholder="Écrivez votre message..." onkeypress="if(event.key==='Enter')sendMessage()">
            <button onclick="sendMessage()">➤</button>
        </div>
        <button class="end-chat" onclick="endChat()">Terminer la conversation</button>
    </div>
    <script>
        const LOGO = "data:image/png;base64,{LOGO_BASE64}";
        let sessionId = localStorage.getItem('taiyari_session') || generateSessionId();
        localStorage.setItem('taiyari_session', sessionId);
        let timeoutChecker = null;
        
        function generateSessionId() {{
            return 'session_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
        }}
        
        function startTimeoutChecker() {{
            if (timeoutChecker) clearInterval(timeoutChecker);
            timeoutChecker = setInterval(checkTimeout, 30000);
        }}
        
        async function checkTimeout() {{
            try {{
                const response = await fetch('/check-timeout', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ session_id: sessionId }})
                }});
                const data = await response.json();
                if (data.timeout_message) {{
                    addBotMessage(data.timeout_message);
                    if (data.closed) clearInterval(timeoutChecker);
                }}
            }} catch (e) {{ console.error(e); }}
        }}
        
        function addBotMessage(text) {{
            const messages = document.getElementById('messages');
            messages.innerHTML += '<div class="message bot"><div class="bot-avatar"><img src="' + LOGO + '" alt="T"></div><div class="bot-text">' + formatMessage(text) + '</div></div>';
            messages.scrollTop = messages.scrollHeight;
        }}
        
        function formatMessage(text) {{
            return text.replace(/(https?:\\/\\/[^\\s]+)/g, '<a href="$1" target="_blank">$1</a>');
        }}
        
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
                const response = await fetch('/chat', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ message, session_id: sessionId }})
                }});
                const data = await response.json();
                document.getElementById('loading-' + loadingId).remove();
                
                if (data.error) {{
                    messages.innerHTML += '<div class="message error">Erreur: ' + escapeHtml(data.error) + '</div>';
                }} else {{
                    messages.innerHTML += '<div class="message bot"><div class="bot-avatar"><img src="' + LOGO + '" alt="T"></div><div class="bot-text">' + formatMessage(data.response) + '</div></div>';
                }}
            }} catch (error) {{
                document.getElementById('loading-' + loadingId).remove();
                messages.innerHTML += '<div class="message error">Erreur de connexion.</div>';
            }}
            messages.scrollTop = messages.scrollHeight;
            startTimeoutChecker();
        }}
        
        async function endChat() {{
            if (confirm('Voulez-vous terminer cette conversation ?')) {{
                try {{
                    const response = await fetch('/end-chat', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ session_id: sessionId }})
                    }});
                    const data = await response.json();
                    addBotMessage(data.message);
                    localStorage.removeItem('taiyari_session');
                    sessionId = generateSessionId();
                    localStorage.setItem('taiyari_session', sessionId);
                }} catch (e) {{ console.error(e); }}
            }}
        }}
        
        function escapeHtml(text) {{ 
            const div = document.createElement('div'); 
            div.textContent = text; 
            return div.innerHTML; 
        }}
        
        startTimeoutChecker();
    </script>
</body>
</html>'''

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy', 
        'service': 'Taiyari',
        'rag_documents': len(rag.documents),
        'rag_last_update': rag.last_update.isoformat() if rag.last_update else None
    })

@app.route('/rag-status')
def rag_status():
    """Check RAG status and trigger update if needed"""
    return jsonify({
        'documents': len(rag.documents),
        'last_update': rag.last_update.isoformat() if rag.last_update else None,
        'is_updating': rag.is_updating,
        'needs_update': rag.needs_update()
    })

@app.route('/rag-update', methods=['POST'])
def rag_update():
    """Manually trigger RAG update"""
    if rag.is_updating:
        return jsonify({'status': 'already_updating'})
    threading.Thread(target=rag.update).start()
    return jsonify({'status': 'update_started'})

@app.route('/check-timeout', methods=['POST'])
def check_timeout_endpoint():
    data = request.json
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({'error': 'No session ID'})
    
    timeout_info = check_session_timeout(session_id)
    if timeout_info:
        return jsonify({'timeout_message': timeout_info['message'], 'closed': timeout_info['type'] == 'closed'})
    return jsonify({'timeout_message': None})

@app.route('/end-chat', methods=['POST'])
def end_chat():
    data = request.json
    session_id = data.get('session_id')
    
    if session_id and session_id in sessions:
        sessions[session_id]['closed'] = True
        threading.Thread(target=send_conversation_copy, args=(session_id,)).start()
        return jsonify({
            'success': True, 
            'message': 'Merci pour cette conversation ! 😊 Une copie a été envoyée par email. N\'hésitez pas à revenir si vous avez d\'autres questions. À bientôt ! 👋'
        })
    
    return jsonify({'success': False, 'message': 'Session non trouvée'})

@app.route('/test-email', methods=['POST'])
def test_email():
    """Test endpoint to verify email configuration"""
    result = send_email(
        'info@marakame.ch',
        'Test Taiyari - Configuration Email',
        '<h1>Test</h1><p>Si vous recevez cet email, la configuration SMTP fonctionne !</p>'
    )
    return jsonify({'success': result})

@app.route('/chat', methods=['POST'])
def chat():
    if not ANTHROPIC_KEY:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured'}), 500
    
    data = request.json
    user_message = data.get('message', '')
    session_id = data.get('session_id', str(uuid.uuid4()))
    
    session_data = get_session(session_id)
    
    # Check session limits BEFORE processing
    limit_check = check_session_limits(session_id)
    if limit_check and limit_check.get('limited'):
        return jsonify({
            'response': limit_check['message'],
            'limited': True,
            'reason': limit_check['reason'],
            'session_id': session_id
        })
    
    update_session_activity(session_id)
    
    # Increment message count
    session_data['message_count'] += 1
    
    is_continuing = len(session_data['messages']) > 0
    
    session_data['messages'].append({
        'role': 'user',
        'content': user_message,
        'timestamp': datetime.now().strftime('%H:%M')
    })
    
    # Detect language more comprehensively
    language = detect_language(user_message)
    
    # Translate query to French for RAG search if not French
    search_query = user_message
    if language != 'fr':
        search_query = translate_to_french_for_rag(user_message, language)
    
    # Check for email in message
    email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', user_message)
    if email_match:
        session_data['visitor_email'] = email_match.group()
    
    # Check for HubSpot email request
    hubspot_email_content = None
    if any(word in user_message.lower() for word in ['email', 'mail', 'envoyé', 'sent', 'message', 'écrit']):
        if email_match:
            emails = get_hubspot_emails(email_match.group())
            if emails:
                for email in emails:
                    if email['body']:
                        hubspot_email_content = f"De: {email_match.group()}\nSujet: {email['subject']}\nContenu: {email['body']}"
                        break
    
    # Check for Shopify order
    order_info = None
    for pattern in [r'#?\d{4,}', r'MK-?\d+']:
        match = re.search(pattern, user_message)
        if match:
            order_info = get_shopify_order(match.group())
            break
    if email_match and not order_info:
        order_info = get_shopify_order(email_match.group())
    
    # RAG search - use translated query for better matching
    context_docs = rag.search(search_query, top_k=5)
    context_parts = []
    for doc in context_docs:
        source = f"[{doc['source'].upper()}]" if doc.get('source') else ""
        url = doc.get('url', '')
        context_parts.append(f"{source} {doc['content'][:1000]}\nURL: {url}")
    context = "\n\n---\n\n".join(context_parts)
    
    if order_info:
        formatted = format_order_info(order_info)
        if formatted:
            context += f"\n\n---\n\nCOMMANDE SHOPIFY: {formatted['order_number']} - Statut: {formatted['status']} - Total: {formatted['total']} - Date: {formatted['created_at']}"
    
    # Build conversation history
    claude_messages = []
    for msg in session_data['messages'][-10:]:
        claude_messages.append({
            "role": msg['role'] if msg['role'] == 'user' else 'assistant',
            "content": msg['content']
        })
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=get_taiyari_prompt(language, context, is_continuing, hubspot_email_content),
        messages=claude_messages
    )
    
    bot_response = response.content[0].text
    
    session_data['messages'].append({
        'role': 'assistant',
        'content': bot_response,
        'timestamp': datetime.now().strftime('%H:%M')
    })
    
    # Check for warnings after response
    limit_check = check_session_limits(session_id)
    warning = limit_check.get('warning') if limit_check else None
    
    # Add warning to response if needed
    if warning:
        bot_response = bot_response + "\n\n" + warning
    
    return jsonify({
        'response': bot_response, 
        'language': language, 
        'session_id': session_id,
        'messages_remaining': MAX_MESSAGES_PER_SESSION - session_data['message_count']
    })

# Initialize RAG on startup
def init_rag():
    print("DEBUG: Initializing RAG on startup...")
    threading.Thread(target=rag.update).start()

# Run initialization
init_rag()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

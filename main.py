from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic
import os
import re
from collections import defaultdict
from datetime import datetime
import requests

app = Flask(__name__)
CORS(app)

# ==================== CONFIGURATION ====================
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY')
SHOPIFY_CLIENT_ID = os.environ.get('SHOPIFY_CLIENT_ID')
SHOPIFY_CLIENT_SECRET = os.environ.get('SHOPIFY_CLIENT_SECRET')
SHOPIFY_SHOP_URL = os.environ.get('SHOPIFY_SHOP_URL', 'marakame.myshopify.com')

# Token cache
shopify_token_cache = {
    'access_token': None,
    'expires_at': 0
}

def get_shopify_token():
    """Get a valid Shopify access token, refreshing if needed"""
    import time
    
    # Check if we have a valid cached token
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
        
        print(f"DEBUG: Token response status: {response.status_code}")
        
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
        'content': 'Marakame propose des bracelets artisanaux faits main par des artisans Huichol du Mexique. Chaque bracelet est unique et créé avec des perles de verre traditionnelles selon la technique ancestrale Wixárika.',
        'content_en': 'Marakame offers handmade artisanal bracelets crafted by Huichol artisans from Mexico. Each bracelet is unique and created with traditional glass beads using the ancestral Wixárika technique.',
        'content_es': 'Marakame ofrece pulseras artesanales hechas a mano por artesanos Huicholes de México. Cada pulsera es única y creada con cuentas de vidrio tradicionales según la técnica ancestral Wixárika.',
        'content_de': 'Marakame bietet handgefertigte Armbänder von Huichol-Kunsthandwerkern aus Mexiko. Jedes Armband ist einzigartig und wird mit traditionellen Glasperlen nach der Wixárika-Technik hergestellt.',
        'content_it': 'Marakame offre braccialetti artigianali fatti a mano da artigiani Huichol del Messico. Ogni braccialetto è unico e creato con perline di vetro tradizionali secondo la tecnica ancestrale Wixárika.',
        'category': 'about',
        'keywords': ['marakame', 'bracelet', 'huichol', 'artisan', 'mexique', 'wixarika', 'perle']
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
        'content': 'Les bracelets Huichol sont fabriqués avec la technique ancestrale du tissage de perles de verre. Chaque motif (peyote, cerf, aigle, soleil) a une signification spirituelle profonde dans la culture Wixárika.',
        'content_en': 'Huichol bracelets are made using the ancestral glass bead weaving technique. Each pattern (peyote, deer, eagle, sun) has deep spiritual meaning in Wixárika culture.',
        'content_es': 'Las pulseras Huichol se fabrican con la técnica ancestral del tejido de cuentas de vidrio. Cada motivo (peyote, venado, águila, sol) tiene un significado espiritual profundo en la cultura Wixárika.',
        'content_de': 'Huichol-Armbänder werden mit der traditionellen Glasperlen-Webtechnik hergestellt. Jedes Muster (Peyote, Hirsch, Adler, Sonne) hat eine tiefe spirituelle Bedeutung.',
        'content_it': 'I braccialetti Huichol sono realizzati con la tecnica ancestrale della tessitura di perline di vetro. Ogni motivo (peyote, cervo, aquila, sole) ha un profondo significato spirituale.',
        'category': 'produits',
        'keywords': ['bracelet', 'huichol', 'perle', 'motif', 'peyote', 'cerf', 'aigle', 'soleil', 'wixarika']
    },
    {
        'content': 'Entretien des bracelets: évitez le contact prolongé avec l\'eau, les parfums et produits chimiques. Rangez-les à plat dans une pochette pour préserver leur forme.',
        'content_en': 'Bracelet care: avoid prolonged contact with water, perfumes and chemicals. Store flat in a pouch to preserve their shape.',
        'content_es': 'Cuidado de las pulseras: evite el contacto prolongado con agua, perfumes y productos químicos. Guárdelas planas en una bolsa.',
        'content_de': 'Armband-Pflege: Vermeiden Sie längeren Kontakt mit Wasser, Parfüms und Chemikalien. Flach in einem Beutel aufbewahren.',
        'content_it': 'Cura dei braccialetti: evitare il contatto prolungato con acqua, profumi e prodotti chimici. Conservare in piano in una custodia.',
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
        'fr': f"""Tu es Taiyari, l'assistant virtuel de Marakame, une boutique suisse de bracelets artisanaux Huichol du Mexique.

PERSONNALITÉ:
- Chaleureux, amical et professionnel
- Utilise des expressions naturelles: "Hmm...", "Voyons voir...", "Ah !"
- Concis et direct (2-3 phrases max)
- Emojis avec parcimonie (1-2 max)
- Vouvoie les clients

CONTEXTE:
{context}

RÈGLES:
1. Réponds UNIQUEMENT avec le contexte fourni
2. Ne jamais inventer d'information
3. Si pas d'info: "Hmm, je n'ai pas cette information. Souhaitez-vous que notre équipe vous recontacte à info@marakame.ch ?"
4. Pour les commandes, demande le numéro ou l'email
5. Reste positif et serviable""",

        'en': f"""You are Taiyari, the virtual assistant for Marakame, a Swiss boutique selling handmade Huichol bracelets from Mexico.

PERSONALITY:
- Warm, friendly and professional
- Use natural expressions: "Hmm...", "Let me see...", "Ah!"
- Concise and direct (2-3 sentences max)
- Emojis sparingly (1-2 max)

CONTEXT:
{context}

RULES:
1. Answer ONLY with provided context
2. Never make up information
3. If no info: "Hmm, I don't have that information. Would you like our team to contact you at info@marakame.ch?"
4. For orders, ask for number or email
5. Stay positive and helpful"""
    }
    return prompts.get(language, prompts['fr'])

# ==================== ENDPOINTS ====================
@app.route('/')
def home():
    return '''<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Taiyari - Assistant Marakame</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px; }
        .chat-container { background: white; border-radius: 20px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); width: 100%; max-width: 420px; overflow: hidden; }
        .chat-header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: white; padding: 16px 20px; display: flex; align-items: center; gap: 12px; }
        .logo { width: 45px; height: 45px; background: white; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #1a1a2e; font-size: 14px; }
        .header-text h1 { font-size: 1.1rem; font-weight: 600; }
        .header-text p { font-size: 0.75rem; opacity: 0.8; margin-top: 2px; }
        .chat-messages { height: 420px; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px; background: #f8f9fa; }
        .message { max-width: 85%; padding: 12px 16px; border-radius: 18px; line-height: 1.5; font-size: 0.95rem; animation: fadeIn 0.3s ease; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .message.user { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; align-self: flex-end; border-bottom-right-radius: 4px; }
        .message.bot { background: white; color: #333; align-self: flex-start; border-bottom-left-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); display: flex; gap: 10px; align-items: flex-start; }
        .bot-avatar { width: 28px; height: 28px; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-radius: 8px; display: flex; align-items: center; justify-content: center; color: white; font-size: 10px; font-weight: bold; flex-shrink: 0; }
        .message.error { background: #fee2e2; color: #dc2626; }
        .loading-dots { display: flex; gap: 4px; padding: 4px 0; }
        .loading-dots span { width: 8px; height: 8px; background: #667eea; border-radius: 50%; animation: bounce 1.4s ease-in-out infinite; }
        .loading-dots span:nth-child(2) { animation-delay: 0.2s; }
        .loading-dots span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes bounce { 0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; } 40% { transform: scale(1); opacity: 1; } }
        .chat-input { display: flex; padding: 16px; border-top: 1px solid #eee; gap: 10px; background: white; }
        .chat-input input { flex: 1; padding: 12px 18px; border: 2px solid #e5e7eb; border-radius: 25px; font-size: 0.95rem; outline: none; transition: border-color 0.2s; }
        .chat-input input:focus { border-color: #667eea; }
        .chat-input button { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; width: 48px; height: 48px; border-radius: 50%; font-size: 1.2rem; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; display: flex; align-items: center; justify-content: center; }
        .chat-input button:hover { transform: scale(1.05); box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4); }
        .chat-input button:disabled { background: #ccc; cursor: not-allowed; transform: none; box-shadow: none; }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">
            <div class="logo">MK</div>
            <div class="header-text">
                <h1>Taiyari</h1>
                <p>Assistant Marakame</p>
            </div>
        </div>
        <div class="chat-messages" id="messages">
            <div class="message bot">
                <div class="bot-avatar">T</div>
                <div>Bonjour ! 👋 Je suis Taiyari, votre assistant Marakame. Comment puis-je vous aider ?</div>
            </div>
        </div>
        <div class="chat-input">
            <input type="text" id="input" placeholder="Écrivez votre message..." onkeypress="if(event.key==='Enter')sendMessage()">
            <button onclick="sendMessage()">➤</button>
        </div>
    </div>
    <script>
        async function sendMessage() {
            const input = document.getElementById('input');
            const messages = document.getElementById('messages');
            const message = input.value.trim();
            if (!message) return;
            messages.innerHTML += '<div class="message user">' + escapeHtml(message) + '</div>';
            input.value = '';
            const loadingId = Date.now();
            messages.innerHTML += '<div class="message bot" id="loading-' + loadingId + '"><div class="bot-avatar">T</div><div class="loading-dots"><span></span><span></span><span></span></div></div>';
            messages.scrollTop = messages.scrollHeight;
            try {
                const response = await fetch('/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message }) });
                const data = await response.json();
                document.getElementById('loading-' + loadingId).remove();
                if (data.error) {
                    messages.innerHTML += '<div class="message error">Erreur: ' + escapeHtml(data.error) + '</div>';
                } else {
                    messages.innerHTML += '<div class="message bot"><div class="bot-avatar">T</div><div>' + escapeHtml(data.response) + '</div></div>';
                }
            } catch (error) {
                document.getElementById('loading-' + loadingId).remove();
                messages.innerHTML += '<div class="message error">Erreur de connexion.</div>';
            }
            messages.scrollTop = messages.scrollHeight;
        }
        function escapeHtml(text) { const div = document.createElement('div'); div.textContent = text; return div.innerHTML; }
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

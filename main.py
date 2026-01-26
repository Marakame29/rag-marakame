from flask import Flask, request, jsonify, session
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

# Session timeout settings
TIMEOUT_WARNING = 5 * 60  # 5 minutes
TIMEOUT_CLOSE = 10 * 60   # 10 minutes

# ==================== SESSION STORAGE ====================
# In production, use Redis or database
sessions = {}

def get_session(session_id):
    if session_id not in sessions:
        sessions[session_id] = {
            'id': session_id,
            'started_at': datetime.now().isoformat(),
            'last_activity': datetime.now(),
            'messages': [],
            'visitor_email': None,
            'greeted': False,
            'warning_sent': False,
            'closed': False
        }
    return sessions[session_id]

def update_session_activity(session_id):
    if session_id in sessions:
        sessions[session_id]['last_activity'] = datetime.now()
        sessions[session_id]['warning_sent'] = False

def check_session_timeout(session_id):
    """Check if session has timed out and return appropriate message"""
    if session_id not in sessions:
        return None
    
    session_data = sessions[session_id]
    if session_data['closed']:
        return None
    
    elapsed = (datetime.now() - session_data['last_activity']).total_seconds()
    
    if elapsed >= TIMEOUT_CLOSE:
        # Close session
        session_data['closed'] = True
        send_conversation_copy(session_id)
        return {
            'type': 'closed',
            'message': "Il semble que vous ne soyez plus connecté. Je ferme cette conversation. Une copie a été envoyée à notre équipe. N'hésitez pas à revenir ! 👋"
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
    """Send email via SMTP"""
    if not SMTP_PASSWORD:
        print("DEBUG: SMTP_PASSWORD not configured")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"Marakame <{SMTP_FROM}>"
        msg['To'] = to_email
        
        html_part = MIMEText(body_html, 'html', 'utf-8')
        msg.attach(html_part)
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())
        
        print(f"DEBUG: Email sent to {to_email}")
        return True
    except Exception as e:
        print(f"DEBUG: Email error: {e}")
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
    """Send conversation copy to info@marakame.ch and visitor if email provided"""
    if session_id not in sessions:
        return
    
    session_data = sessions[session_id]
    if not session_data['messages']:
        return
    
    html_content = format_conversation_html(session_data)
    subject = f"Conversation Taiyari - {session_data['started_at'][:10]}"
    
    # Send to info@marakame.ch
    send_email('info@marakame.ch', subject, html_content)
    
    # Send to visitor if email provided
    if session_data.get('visitor_email'):
        visitor_subject = "Copie de votre conversation avec Marakame"
        send_email(session_data['visitor_email'], visitor_subject, html_content)

# ==================== HUBSPOT FUNCTIONS ====================
def search_hubspot_contact(email):
    """Search for a contact in HubSpot by email"""
    if not HUBSPOT_API_KEY:
        print("DEBUG: HUBSPOT_API_KEY not configured")
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
        print(f"DEBUG: HubSpot contact search status: {response.status_code}")
        
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
        print("DEBUG: HUBSPOT_API_KEY not configured")
        return []
    
    try:
        # First find the contact
        contact = search_hubspot_contact(email)
        if not contact:
            print(f"DEBUG: No HubSpot contact found for {email}")
            return []
        
        contact_id = contact['id']
        
        # Get email engagements for this contact
        url = f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}/associations/emails"
        headers = {
            'Authorization': f'Bearer {HUBSPOT_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        print(f"DEBUG: HubSpot emails association status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"DEBUG: HubSpot association error: {response.text}")
            return []
        
        associations = response.json().get('results', [])
        print(f"DEBUG: Found {len(associations)} email associations")
        
        if not associations:
            return []
        
        # Get email details with all properties
        emails = []
        for assoc in associations[:5]:  # Limit to 5 most recent
            email_id = assoc.get('id') or assoc.get('toObjectId')
            if not email_id:
                continue
                
            email_url = f"https://api.hubapi.com/crm/v3/objects/emails/{email_id}?properties=hs_email_subject,hs_email_text,hs_email_html,hs_email_body,hs_timestamp,hs_email_direction,hs_body_preview"
            email_response = requests.get(email_url, headers=headers, timeout=10)
            
            print(f"DEBUG: Email {email_id} fetch status: {email_response.status_code}")
            
            if email_response.status_code == 200:
                email_data = email_response.json()
                props = email_data.get('properties', {})
                print(f"DEBUG: Email properties: {list(props.keys())}")
                
                # Try multiple fields for body content
                body = props.get('hs_email_text') or props.get('hs_email_html') or props.get('hs_email_body') or props.get('hs_body_preview') or ''
                
                # Clean HTML if present
                if '<' in body and '>' in body:
                    body = re.sub(r'<[^>]+>', ' ', body)
                    body = re.sub(r'\s+', ' ', body).strip()
                
                emails.append({
                    'subject': props.get('hs_email_subject', 'Sans sujet'),
                    'body': body[:500] if body else 'Contenu non disponible',
                    'date': props.get('hs_timestamp', ''),
                    'direction': props.get('hs_email_direction', '')
                })
        
        print(f"DEBUG: Retrieved {len(emails)} emails with content")
        return emails
    except Exception as e:
        print(f"DEBUG: HubSpot emails error: {e}")
        return []

# ==================== SHOPIFY TOKEN ====================
shopify_token_cache = {
    'access_token': None,
    'expires_at': 0
}

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
        'category': 'about',
        'keywords': ['marakame', 'bijoux', 'jewelry', 'accessoires', 'artisan', 'mexique', 'colombie', 'wayuu', 'boucles', 'bagues', 'colliers']
    },
    {
        'content': 'Livraison en Suisse: gratuite dès 50 CHF, délai de 2-4 jours ouvrables. Livraison internationale (France, Allemagne, etc.): 5-10 jours ouvrables, frais calculés à la commande.',
        'content_en': 'Delivery in Switzerland: free from 50 CHF, 2-4 business days. International delivery (France, Germany, etc.): 5-10 business days, fees calculated at checkout.',
        'category': 'livraison',
        'keywords': ['livraison', 'delivery', 'shipping', 'suisse', 'international', 'france', 'délai', 'jours']
    },
    {
        'content': 'Modes de paiement acceptés: carte de crédit (Visa, Mastercard, American Express), PayPal, Twint, et virement bancaire. Tous les paiements sont 100% sécurisés.',
        'content_en': 'Accepted payment methods: credit card (Visa, Mastercard, American Express), PayPal, Twint, and bank transfer. All payments are 100% secure.',
        'category': 'paiement',
        'keywords': ['paiement', 'payment', 'carte', 'credit', 'paypal', 'twint', 'visa', 'mastercard']
    },
    {
        'content': 'Retours acceptés sous 30 jours après réception. Le produit doit être dans son état original avec emballage. Contactez info@marakame.ch pour initier un retour. Remboursement sous 5-7 jours après réception.',
        'content_en': 'Returns accepted within 30 days of receipt. Product must be in original condition with packaging. Contact info@marakame.ch to initiate a return. Refund within 5-7 days after receipt.',
        'category': 'retours',
        'keywords': ['retour', 'return', 'remboursement', 'refund', '30 jours', 'échange']
    },
    {
        'content': 'Nos bijoux (boucles d\'oreilles, bagues, colliers) sont fabriqués avec des matériaux de qualité par des artisanes. L\'origine (Mexique ou Colombie) est indiquée sur chaque page produit sous "Made in". Les bracelets et sacs Wayuu sont tissés à la main par des artisanes colombiennes de la communauté Wayuu.',
        'content_en': 'Our jewelry (earrings, rings, necklaces) is crafted with quality materials by artisans. The origin (Mexico or Colombia) is indicated on each product page under "Made in". Wayuu bracelets and bags are hand-woven by Colombian artisans from the Wayuu community.',
        'category': 'produits',
        'keywords': ['bijoux', 'jewelry', 'boucles', 'earrings', 'bagues', 'rings', 'colliers', 'necklaces', 'wayuu', 'sac', 'bag', 'bracelet']
    },
    {
        'content': 'Entretien des bijoux: évitez le contact prolongé avec l\'eau, les parfums et produits chimiques. Rangez-les dans une pochette pour préserver leur éclat.',
        'content_en': 'Jewelry care: avoid prolonged contact with water, perfumes and chemicals. Store in a pouch to preserve their shine.',
        'category': 'entretien',
        'keywords': ['entretien', 'care', 'nettoyage', 'eau', 'water', 'rangement']
    },
    {
        'content': 'Pour suivre votre commande, connectez-vous à votre compte sur marakame.ch ou utilisez le lien de suivi envoyé par email. Si vous n\'avez pas reçu d\'email, vérifiez vos spams ou contactez info@marakame.ch.',
        'content_en': 'To track your order, log in to your account on marakame.ch or use the tracking link sent by email. Contact info@marakame.ch if needed.',
        'category': 'commande',
        'keywords': ['commande', 'order', 'suivi', 'tracking', 'email', 'compte']
    },
]

# ==================== LANGUAGE DETECTION ====================
def detect_language(text):
    text_lower = text.lower()
    
    fr_words = ['bonjour', 'merci', 'commande', 'livraison', 'comment', 'quand', 'où', 'pourquoi', 'je', 'mon', 'ma', 'une', 'des', 'les', 'pour', 'avec']
    en_words = ['hello', 'hi', 'thanks', 'order', 'delivery', 'how', 'when', 'where', 'what', 'my', 'the', 'is', 'are', 'can', 'could']
    
    scores = {
        'fr': sum(1 for w in fr_words if w in text_lower),
        'en': sum(1 for w in en_words if w in text_lower),
    }
    
    max_score = max(scores.values())
    if max_score == 0:
        return 'fr'
    return max(scores, key=scores.get)

# ==================== RAG ====================
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
            for lang_key in ['content', 'content_en']:
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
        lang_key = 'content_en' if language == 'en' else 'content'
        
        for doc_id, score in ranked[:top_k]:
            doc = self.documents[doc_id]
            content = doc.get(lang_key, doc.get('content', ''))
            results.append({'content': content, 'category': doc.get('category', ''), 'score': score})
        return results

rag = MultilingualRAG()
rag.add_documents(FAQ_DATA)

# ==================== SHOPIFY ====================
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

def format_order_info(order, language='fr'):
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
def get_taiyari_prompt(language, context, is_new_conversation=True):
    greeting_instruction = "" if is_new_conversation else "NE PAS dire 'Bonjour' ou resaluer - la conversation est déjà en cours."
    
    return f"""Tu es Taiyari, l'assistant virtuel de Marakame, une boutique suisse de bijoux et accessoires artisanaux.

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
1. NE JAMAIS utiliser le mot "Huichol"
2. {greeting_instruction}
3. Réponds UNIQUEMENT avec le contexte fourni
4. Ne jamais inventer d'information
5. Pour l'origine d'un produit, référer à la page produit
6. Si pas d'info: proposer de contacter info@marakame.ch
7. Pour les commandes, demande le numéro ou l'email
8. Pour les emails HubSpot, demande l'adresse email utilisée pour l'envoi

CONTEXTE:
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
                <div>Bonjour ! 👋 Je suis Taiyari, votre assistant Marakame. Comment puis-je vous aider ?</div>
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
        let lastActivity = Date.now();
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
                    if (data.closed) {{
                        clearInterval(timeoutChecker);
                    }}
                }}
            }} catch (e) {{ console.error(e); }}
        }}
        
        function addBotMessage(text) {{
            const messages = document.getElementById('messages');
            messages.innerHTML += '<div class="message bot"><div class="bot-avatar"><img src="' + LOGO + '" alt="T"></div><div>' + escapeHtml(text) + '</div></div>';
            messages.scrollTop = messages.scrollHeight;
        }}
        
        async function sendMessage() {{
            const input = document.getElementById('input');
            const messages = document.getElementById('messages');
            const message = input.value.trim();
            if (!message) return;
            
            lastActivity = Date.now();
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
                    messages.innerHTML += '<div class="message bot"><div class="bot-avatar"><img src="' + LOGO + '" alt="T"></div><div>' + escapeHtml(data.response) + '</div></div>';
                }}
            }} catch (error) {{
                document.getElementById('loading-' + loadingId).remove();
                messages.innerHTML += '<div class="message error">Erreur de connexion.</div>';
            }}
            messages.scrollTop = messages.scrollHeight;
            startTimeoutChecker();
        }}
        
        async function endChat() {{
            if (confirm('Voulez-vous terminer cette conversation ? Une copie sera envoyée par email.')) {{
                try {{
                    const response = await fetch('/end-chat', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ session_id: sessionId }})
                    }});
                    const data = await response.json();
                    addBotMessage(data.message || 'Conversation terminée. Merci et à bientôt ! 👋');
                    localStorage.removeItem('taiyari_session');
                    sessionId = generateSessionId();
                    localStorage.setItem('taiyari_session', sessionId);
                }} catch (e) {{
                    console.error(e);
                }}
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
    return jsonify({'status': 'healthy', 'service': 'Taiyari'})

@app.route('/conversations')
def get_conversations():
    return jsonify({'total': len(conversations), 'conversations': conversations[-100:]})

@app.route('/check-timeout', methods=['POST'])
def check_timeout():
    data = request.json
    session_id = data.get('session_id')
    
    if not session_id:
        return jsonify({'error': 'No session ID'})
    
    timeout_info = check_session_timeout(session_id)
    
    if timeout_info:
        return jsonify({
            'timeout_message': timeout_info['message'],
            'closed': timeout_info['type'] == 'closed'
        })
    
    return jsonify({'timeout_message': None})

@app.route('/end-chat', methods=['POST'])
def end_chat():
    data = request.json
    session_id = data.get('session_id')
    
    if session_id and session_id in sessions:
        sessions[session_id]['closed'] = True
        send_conversation_copy(session_id)
        return jsonify({'success': True, 'message': 'Merci pour cette conversation ! Une copie a été envoyée. À bientôt ! 👋'})
    
    return jsonify({'success': False, 'message': 'Session non trouvée'})

@app.route('/chat', methods=['POST'])
def chat():
    if not ANTHROPIC_KEY:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured'}), 500
    
    data = request.json
    user_message = data.get('message', '')
    session_id = data.get('session_id', str(uuid.uuid4()))
    
    # Get or create session
    session_data = get_session(session_id)
    update_session_activity(session_id)
    
    # Check if this is the first message (greeting already shown in UI)
    is_new_conversation = len(session_data['messages']) == 0
    session_data['greeted'] = True
    
    # Store user message
    session_data['messages'].append({
        'role': 'user',
        'content': user_message,
        'timestamp': datetime.now().strftime('%H:%M')
    })
    
    language = detect_language(user_message)
    
    # Check for email in message and store it
    email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', user_message)
    if email_match:
        session_data['visitor_email'] = email_match.group()
    
    # Check for HubSpot email request
    hubspot_context = ""
    if any(word in user_message.lower() for word in ['email', 'mail', 'envoyé', 'sent', 'message']):
        if email_match:
            emails = get_hubspot_emails(email_match.group())
            if emails:
                hubspot_context = "\n\nEMAILS TROUVÉS DANS HUBSPOT:\n"
                for email in emails[:3]:
                    hubspot_context += f"- Sujet: {email['subject']}\n  Contenu: {email['body'][:200]}...\n"
    
    # Check for Shopify order
    order_info = None
    for pattern in [r'#?\d{4,}', r'MK-?\d+']:
        match = re.search(pattern, user_message)
        if match:
            order_info = get_shopify_order(match.group())
            break
    if email_match and not order_info:
        order_info = get_shopify_order(email_match.group())
    
    # RAG search
    context_docs = rag.search(user_message, language=language, top_k=3)
    context = "\n".join([doc['content'] for doc in context_docs])
    
    if order_info:
        formatted = format_order_info(order_info, language)
        if formatted:
            context += f"\n\nCOMMANDE: {formatted['order_number']} - Statut: {formatted['status']} - Total: {formatted['total']} - Date: {formatted['created_at']}"
    
    context += hubspot_context
    
    # Build conversation history for Claude
    claude_messages = []
    for msg in session_data['messages'][-10:]:  # Last 10 messages for context
        claude_messages.append({
            "role": msg['role'] if msg['role'] == 'user' else 'assistant',
            "content": msg['content']
        })
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=get_taiyari_prompt(language, context, is_new_conversation),
        messages=claude_messages
    )
    
    bot_response = response.content[0].text
    
    # Store bot response
    session_data['messages'].append({
        'role': 'assistant',
        'content': bot_response,
        'timestamp': datetime.now().strftime('%H:%M')
    })
    
    log_conversation(user_message, bot_response, language)
    
    return jsonify({'response': bot_response, 'language': language, 'session_id': session_id})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

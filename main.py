from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic
import os
import re
from collections import defaultdict
from datetime import datetime
import requests
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import uuid
import threading

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
    if session_id not in sessions:
        return None
    
    session_data = sessions[session_id]
    if session_data['closed']:
        return None
    
    elapsed = (datetime.now() - session_data['last_activity']).total_seconds()
    
    if elapsed >= TIMEOUT_CLOSE:
        session_data['closed'] = True
        # Send email in background thread
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
    """Send email via SMTP"""
    if not SMTP_PASSWORD:
        print("DEBUG: SMTP_PASSWORD not configured")
        return False
    
    try:
        print(f"DEBUG: Attempting to send email to {to_email}")
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"Marakame <{SMTP_FROM}>"
        msg['To'] = to_email
        
        html_part = MIMEText(body_html, 'html', 'utf-8')
        msg.attach(html_part)
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())
        
        print(f"DEBUG: Email sent successfully to {to_email}")
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
        print(f"DEBUG: HubSpot emails association status: {response.status_code}")
        
        if response.status_code != 200:
            return []
        
        associations = response.json().get('results', [])
        print(f"DEBUG: Found {len(associations)} email associations")
        
        if not associations:
            return []
        
        emails = []
        for assoc in associations[:5]:
            email_id = assoc.get('id') or assoc.get('toObjectId')
            if not email_id:
                continue
                
            email_url = f"https://api.hubapi.com/crm/v3/objects/emails/{email_id}?properties=hs_email_subject,hs_email_text,hs_email_html,hs_email_body,hs_timestamp,hs_email_direction,hs_body_preview"
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
        
        print(f"DEBUG: Retrieved {len(emails)} emails")
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

# ==================== FAQ DATA - COMPLETE FROM MARAKAME.CH ====================
FAQ_DATA = [
    # === ABOUT ===
    {
        'content': 'Marakame est une boutique suisse proposant des bijoux et accessoires artisanaux faits main. Nos créations incluent des boucles d\'oreilles, bagues, colliers, bracelets Wayuu et sacs Wayuu. Chaque pièce est unique, fabriquée par des artisanes au Mexique ou en Colombie (l\'origine est indiquée sur chaque page produit sous "Made in").',
        'category': 'about',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['marakame', 'bijoux', 'accessoires', 'artisan', 'mexique', 'colombie', 'wayuu', 'boutique', 'suisse']
    },
    # === COMMANDE ET SUIVI ===
    {
        'content': 'Une fois votre commande validée, vous recevez un e-mail de confirmation. Dès que votre commande est expédiée, un e-mail contenant les informations de suivi vous est envoyé.',
        'category': 'commande',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['commande', 'suivi', 'confirmation', 'email', 'expédition', 'où en est']
    },
    {
        'content': 'Lorsque votre commande est expédiée, un lien de suivi vous est communiqué par e-mail afin de suivre l\'acheminement de votre colis en temps réel.',
        'category': 'commande',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['suivi', 'livraison', 'tracking', 'colis', 'temps réel']
    },
    {
        'content': 'Les commandes peuvent être modifiées ou annulées dans un délai de 12 à 24 heures après validation, tant qu\'elles n\'ont pas encore été expédiées. Contactez-nous rapidement par e-mail à info@marakame.ch.',
        'category': 'commande',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['modifier', 'annuler', 'commande', 'annulation', 'modification']
    },
    # === LIVRAISON ===
    {
        'content': 'Les commandes sont généralement préparées sous 1 à 3 jours ouvrables. Délais de livraison: Suisse: 2 à 5 jours ouvrables. International (France, Belgique, Espagne, etc.): 5 à 10 jours ouvrables.',
        'category': 'livraison',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['délai', 'livraison', 'jours', 'suisse', 'international', 'france', 'belgique']
    },
    {
        'content': 'Oui, nous livrons en Suisse ainsi que dans plusieurs pays à l\'international. Les options disponibles s\'affichent lors du passage en caisse.',
        'category': 'livraison',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['livraison', 'international', 'pays', 'suisse']
    },
    {
        'content': 'La livraison est gratuite en Suisse dès CHF 80.– d\'achat. En dessous de ce montant ou pour les livraisons internationales, les frais sont calculés automatiquement lors du paiement.',
        'category': 'livraison',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['frais', 'livraison', 'gratuit', 'gratuite', '80', 'chf', 'prix']
    },
    {
        'content': 'Si un article présente un défaut ou un dommage à la réception, veuillez nous contacter dans les 48 heures avec des photos du bijou concerné à info@marakame.ch. Nous procéderons à une analyse et proposerons, selon le cas, un échange, une réparation ou un remboursement.',
        'category': 'livraison',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['endommagé', 'défaut', 'dommage', 'cassé', 'abîmé', 'réception']
    },
    # === MATÉRIAUX ET PRODUITS ===
    {
        'content': 'Oui, tous les bijoux Marakame sont faits à la main par des artisanes, avec soin et attention aux détails.',
        'category': 'produits',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['fait main', 'handmade', 'artisanal', 'artisane']
    },
    {
        'content': '''Les matériaux varient selon les créations: plaqué or, bronze, acier inoxydable, perles Miyuki, pierres naturelles, etc. Les détails précis sont indiqués sur chaque fiche produit.

Perles Miyuki: Petites perles en verre uniformes japonaises, souvent aux couleurs vives et à la finition brillante, idéales pour le tissage.

Perles de verre/tchèques: Perles en verre de formes variées, souvent colorées et transparentes, avec un fini lisse et brillant. Fabriquées en République tchèque.

Lapis lazuli: Pierre précieuse bleu profond avec des inclusions dorées de pyrite. Associée à la sagesse et à la vérité.

Jade: Pierre verte (peut varier du blanc au violet), avec un éclat doux. Symbolise la pureté et l'harmonie.

Citrine: Pierre jaune doré à orange, transparente. Représente l'abondance et la créativité.

Corail rouge: Pierre rouge à rouge orangé. Symbolise la vitalité et la protection.

Onyx: Pierre noir profond. Associée à la force et à la stabilité émotionnelle.''',
        'category': 'materiaux',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['matériau', 'matériaux', 'material', 'plaqué or', 'bronze', 'acier', 'perle', 'miyuki', 'pierre', 'lapis', 'jade', 'citrine', 'corail', 'onyx', 'verre', 'tchèque']
    },
    {
        'content': 'Nos bijoux sont sélectionnés pour être confortables au quotidien. La majorité est sans nickel, mais en cas d\'allergie spécifique à certains matériaux, nous conseillons de consulter la description du produit ou de nous contacter à info@marakame.ch.',
        'category': 'produits',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['hypoallergénique', 'allergie', 'nickel', 'sensible', 'peau']
    },
    {
        'content': 'Pour préserver la qualité et la durabilité des bijoux, nous recommandons d\'éviter le contact avec l\'eau, le parfum, les lotions et la transpiration excessive.',
        'category': 'entretien',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['eau', 'water', 'résistant', 'parfum', 'quotidien', 'douche', 'bain']
    },
    # === TAILLES ===
    {
        'content': 'Les dimensions et informations de taille sont indiquées sur chaque fiche produit. Certaines bagues sont ajustables pour plus de flexibilité.',
        'category': 'taille',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['taille', 'dimension', 'ajustable', 'mesure', 'bague', 'bracelet']
    },
    {
        'content': 'Si la taille ne convient pas, contactez-nous dans les 14 jours suivant la réception à info@marakame.ch afin de trouver une solution (échange ou retour).',
        'category': 'taille',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['taille', 'convient pas', 'échange', 'retour', 'trop grand', 'trop petit']
    },
    {
        'content': 'Oui, les échanges sont possibles sous réserve de disponibilité et à condition que le bijou n\'ait pas été porté ou endommagé.',
        'category': 'retours',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['échange', 'échanger', 'autre modèle', 'autre taille']
    },
    # === RETOURS ET REMBOURSEMENTS ===
    {
        'content': 'Les retours sont acceptés dans un délai de 14 jours après réception. Les bijoux doivent être non portés et dans leur emballage d\'origine. Le remboursement est effectué après réception et vérification du produit.',
        'category': 'retours',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['retour', 'retourner', 'remboursement', 'rembourser', '14 jours', 'politique']
    },
    {
        'content': 'Si vous recevez un bijou endommagé ou incorrect, contactez-nous dès réception avec une photo du produit concerné à info@marakame.ch. Nous vous proposerons un remplacement ou un remboursement.',
        'category': 'retours',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['endommagé', 'incorrect', 'erreur', 'mauvais', 'cassé']
    },
    # === ENTRETIEN ===
    {
        'content': 'Rangez vos bijoux à l\'abri de l\'humidité, évitez le contact avec les liquides et nettoyez-les délicatement avec un chiffon doux.',
        'category': 'entretien',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['entretien', 'entretenir', 'nettoyer', 'ranger', 'conserver', 'préserver', 'chiffon']
    },
    # === PAIEMENT ===
    {
        'content': 'Nous acceptons les principales cartes de crédit (Visa, Mastercard, American Express), ainsi que Google Pay, Apple Pay, PayPal.',
        'category': 'paiement',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['paiement', 'carte', 'visa', 'mastercard', 'paypal', 'apple pay', 'google pay', 'payer']
    },
    {
        'content': 'Oui, toutes les transactions sont sécurisées via des systèmes de paiement cryptés conformes aux standards de sécurité.',
        'category': 'paiement',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['sécurisé', 'sécurité', 'paiement', 'crypté', 'sûr']
    },
    # === CADEAUX ===
    {
        'content': 'Oui, nos bijoux sont soigneusement emballés et peuvent être offerts directement. N\'hésitez pas à nous contacter pour une demande spéciale à info@marakame.ch.',
        'category': 'cadeau',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['cadeau', 'offrir', 'emballage', 'gift', 'présent']
    },
    # === CONTACT ===
    {
        'content': 'Vous pouvez nous écrire à info@marakame.ch. Nous répondons généralement sous 24 à 48 heures ouvrables. Adresse: 1213 Petit-Lancy, Genève (CH).',
        'category': 'contact',
        'url': 'https://marakame.ch/pages/faq',
        'keywords': ['contact', 'contacter', 'email', 'adresse', 'joindre', 'écrire']
    },
]

# ==================== LANGUAGE DETECTION ====================
def detect_language(text):
    text_lower = text.lower()
    fr_words = ['bonjour', 'merci', 'commande', 'livraison', 'comment', 'quand', 'où', 'pourquoi', 'je', 'mon', 'ma', 'une', 'des', 'les', 'pour', 'avec', 'quel', 'quelle']
    en_words = ['hello', 'hi', 'thanks', 'order', 'delivery', 'how', 'when', 'where', 'what', 'my', 'the', 'is', 'are', 'can', 'could']
    
    scores = {
        'fr': sum(1 for w in fr_words if w in text_lower),
        'en': sum(1 for w in en_words if w in text_lower),
    }
    
    return 'en' if scores['en'] > scores['fr'] else 'fr'

# ==================== RAG ====================
class MultilingualRAG:
    def __init__(self):
        self.documents = []
        self.index = defaultdict(list)
    
    def add_documents(self, docs):
        for doc in docs:
            doc_id = len(self.documents)
            self.documents.append(doc)
            for kw in doc.get('keywords', []):
                self.index[kw.lower()].append(doc_id)
            words = self._tokenize(doc['content'])
            for word in set(words):
                if len(word) > 2:
                    self.index[word].append(doc_id)
    
    def _tokenize(self, text):
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        return text.split()
    
    def search(self, query, top_k=3):
        query_words = self._tokenize(query)
        scores = defaultdict(float)
        
        for word in query_words:
            if word in self.index:
                for doc_id in self.index[word]:
                    scores[doc_id] += 1
        
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        results = []
        
        for doc_id, score in ranked[:top_k]:
            doc = self.documents[doc_id]
            results.append({
                'content': doc['content'],
                'category': doc.get('category', ''),
                'url': doc.get('url', ''),
                'score': score
            })
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
    continuation_rule = "NE PAS saluer à nouveau (pas de 'Bonjour', 'Hello', etc.) - la conversation est déjà en cours." if is_continuing else ""
    
    hubspot_instruction = ""
    if hubspot_email_content:
        hubspot_instruction = f"""
EMAIL DU CLIENT TROUVÉ DANS HUBSPOT:
{hubspot_email_content}

Tu dois RÉPONDRE à cette question en utilisant les informations de la FAQ ci-dessous. Ne dis pas que tu n'as pas l'information si elle est dans le contexte."""

    return f"""Tu es Taiyari, l'assistant virtuel de Marakame, une boutique suisse de bijoux et accessoires artisanaux faits main.

PRODUITS MARAKAME:
- Bijoux: boucles d'oreilles, bagues, colliers
- Accessoires: bracelets Wayuu, sacs Wayuu
- Fabriqués par des artisanes au Mexique ou en Colombie (voir "Made in" sur chaque page produit)

PERSONNALITÉ:
- Chaleureux, amical et professionnel
- Expressions naturelles: "Hmm...", "Voyons voir...", "Ah !"
- Concis: 2-3 phrases max pour les réponses simples
- Emojis avec parcimonie (1-2 max)
- Vouvoie les clients

RÈGLES STRICTES:
1. NE JAMAIS utiliser le mot "Huichol"
2. {continuation_rule}
3. TOUJOURS chercher la réponse dans le CONTEXTE avant de dire que tu ne sais pas
4. Si la question est GÉNÉRALE (ex: "quels matériaux?"), donne un résumé court (2-3 lignes) + le lien vers la page FAQ
5. Si la question est PRÉCISE (ex: "c'est quoi le lapis lazuli?"), réponds directement avec les détails
6. Ne rediriger vers info@marakame.ch QUE si la réponse n'est PAS dans le contexte
7. Pour les commandes, demande le numéro ou l'email si non fourni
{hubspot_instruction}

CONTEXTE FAQ:
{context}"""

# ==================== LOGO ====================
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
    return jsonify({'status': 'healthy', 'service': 'Taiyari'})

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
        # Send email in background thread to avoid timeout
        threading.Thread(target=send_conversation_copy, args=(session_id,)).start()
        return jsonify({
            'success': True, 
            'message': 'Merci pour cette conversation ! 😊 Une copie a été envoyée par email. N\'hésitez pas à revenir si vous avez d\'autres questions. À bientôt ! 👋'
        })
    
    return jsonify({'success': False, 'message': 'Session non trouvée'})

@app.route('/chat', methods=['POST'])
def chat():
    if not ANTHROPIC_KEY:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured'}), 500
    
    data = request.json
    user_message = data.get('message', '')
    session_id = data.get('session_id', str(uuid.uuid4()))
    
    session_data = get_session(session_id)
    update_session_activity(session_id)
    
    is_continuing = len(session_data['messages']) > 0
    
    session_data['messages'].append({
        'role': 'user',
        'content': user_message,
        'timestamp': datetime.now().strftime('%H:%M')
    })
    
    language = detect_language(user_message)
    
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
    
    # RAG search
    context_docs = rag.search(user_message, top_k=3)
    context_parts = []
    for doc in context_docs:
        context_parts.append(f"{doc['content']}\n(Source: {doc['url']})")
    context = "\n\n".join(context_parts)
    
    if order_info:
        formatted = format_order_info(order_info)
        if formatted:
            context += f"\n\nCOMMANDE SHOPIFY: {formatted['order_number']} - Statut: {formatted['status']} - Total: {formatted['total']} - Date: {formatted['created_at']}"
    
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
    
    return jsonify({'response': bot_response, 'language': language, 'session_id': session_id})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

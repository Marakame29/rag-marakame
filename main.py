from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic
import os
import re
from collections import defaultdict

app = Flask(__name__)
CORS(app)

# ==================== CONFIGURATION ====================
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY')

# ==================== FAQ DATA (votre base de connaissances) ====================
FAQ_DATA = [
    {
        'content': 'Marakame propose des bracelets artisanaux faits main par des artisans Huichol du Mexique. Chaque bracelet est unique et créé avec des perles de verre traditionnelles.',
        'category': 'about'
    },
    {
        'content': 'Livraison Suisse: gratuite dès 50 CHF. Délai: 3-5 jours ouvrables. Livraison internationale: 5-10 jours ouvrables.',
        'category': 'livraison'
    },
    {
        'content': 'Paiements acceptés: carte de crédit (Visa, Mastercard), PayPal, et Twint. Tous les paiements sont sécurisés.',
        'category': 'paiement'
    },
    {
        'content': 'Retours acceptés sous 30 jours. Le produit doit être dans son état original. Contactez-nous à contact@marakame.ch pour initier un retour.',
        'category': 'retours'
    },
    {
        'content': 'Les bracelets Huichol sont fabriqués avec la technique ancestrale du tissage de perles. Chaque motif a une signification spirituelle dans la culture Wixárika.',
        'category': 'produits'
    },
    {
        'content': 'Pour l\'entretien des bracelets: évitez le contact avec l\'eau et les produits chimiques. Rangez-les à plat pour préserver leur forme.',
        'category': 'entretien'
    },
]

# ==================== RAG SIMPLE (BM25-like) ====================
class SimpleRAG:
    def __init__(self):
        self.documents = []
        self.index = defaultdict(list)
    
    def add_documents(self, docs):
        for doc in docs:
            doc_id = len(self.documents)
            self.documents.append(doc)
            words = self._tokenize(doc['content'])
            for word in set(words):
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
            results.append({
                'content': self.documents[doc_id]['content'],
                'category': self.documents[doc_id].get('category', ''),
                'score': score
            })
        return results

# Initialiser le RAG
rag = SimpleRAG()
rag.add_documents(FAQ_DATA)

# ==================== ENDPOINTS ====================
@app.route('/')
def home():
    return jsonify({
        'status': 'ok',
        'message': 'RAG Marakame API is running',
        'endpoints': {
            '/chat': 'POST - Envoyer un message',
            '/search': 'POST - Rechercher dans la FAQ',
            '/health': 'GET - Status'
        }
    })

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})

@app.route('/search', methods=['POST'])
def search():
    data = request.json
    query = data.get('query', '')
    results = rag.search(query)
    return jsonify({'results': results})

@app.route('/chat', methods=['POST'])
def chat():
    if not ANTHROPIC_KEY:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured'}), 500
    
    data = request.json
    user_message = data.get('message', '')
    
    # Rechercher le contexte pertinent
    context_docs = rag.search(user_message, top_k=3)
    context = "\n".join([doc['content'] for doc in context_docs])
    
    # Appeler Claude
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    
    system_prompt = f"""Tu es l'assistant virtuel de Marakame, une boutique suisse de bracelets artisanaux Huichol du Mexique.

CONTEXTE (informations de notre base de données):
{context}

INSTRUCTIONS:
- Réponds en français, de manière amicale et professionnelle
- Base tes réponses sur le contexte fourni
- Si tu ne trouves pas l'information, dis-le poliment et propose de contacter contact@marakame.ch
- Sois concis mais complet"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    
    return jsonify({
        'response': response.content[0].text,
        'context_used': context_docs
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

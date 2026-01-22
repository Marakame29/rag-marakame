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
    return '''<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test RAG Marakame</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px; }
        .chat-container { background: white; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,0.1); width: 100%; max-width: 500px; overflow: hidden; }
        .chat-header { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 20px; text-align: center; }
        .chat-header h1 { font-size: 1.25rem; font-weight: 600; }
        .chat-header p { font-size: 0.875rem; opacity: 0.9; margin-top: 4px; }
        .chat-messages { height: 400px; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px; }
        .message { max-width: 85%; padding: 12px 16px; border-radius: 16px; line-height: 1.5; }
        .message.user { background: #6366f1; color: white; align-self: flex-end; border-bottom-right-radius: 4px; }
        .message.bot { background: #f0f0f0; color: #333; align-self: flex-start; border-bottom-left-radius: 4px; }
        .message.error { background: #fee2e2; color: #dc2626; }
        .message.loading { background: #f0f0f0; color: #666; }
        .chat-input { display: flex; padding: 16px; border-top: 1px solid #eee; gap: 12px; }
        .chat-input input { flex: 1; padding: 12px 16px; border: 1px solid #ddd; border-radius: 24px; font-size: 1rem; outline: none; }
        .chat-input input:focus { border-color: #6366f1; }
        .chat-input button { background: #6366f1; color: white; border: none; padding: 12px 24px; border-radius: 24px; font-size: 1rem; cursor: pointer; font-weight: 500; }
        .chat-input button:hover { background: #4f46e5; }
        .chat-input button:disabled { background: #ccc; cursor: not-allowed; }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">
            <h1>🧵 Marakame Assistant</h1>
            <p>Testez votre RAG</p>
        </div>
        <div class="chat-messages" id="messages">
            <div class="message bot">Bonjour ! Je suis l\'assistant Marakame. Posez-moi vos questions sur nos bracelets, la livraison, les retours...</div>
        </div>
        <div class="chat-input">
            <input type="text" id="input" placeholder="Votre question..." onkeypress="if(event.key===\'Enter\')sendMessage()">
            <button onclick="sendMessage()">Envoyer</button>
        </div>
    </div>
    <script>
        async function sendMessage() {
            const input = document.getElementById('input');
            const messages = document.getElementById('messages');
            const message = input.value.trim();
            if (!message) return;
            messages.innerHTML += `<div class="message user">${message}</div>`;
            input.value = '';
            const loadingId = Date.now();
            messages.innerHTML += `<div class="message loading" id="loading-${loadingId}">...</div>`;
            messages.scrollTop = messages.scrollHeight;
            try {
                const response = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message })
                });
                const data = await response.json();
                document.getElementById(`loading-${loadingId}`).remove();
                if (data.error) {
                    messages.innerHTML += `<div class="message error">Erreur: ${data.error}</div>`;
                } else {
                    messages.innerHTML += `<div class="message bot">${data.response}</div>`;
                }
            } catch (error) {
                document.getElementById(`loading-${loadingId}`).remove();
                messages.innerHTML += `<div class="message error">Erreur: ${error.message}</div>`;
            }
            messages.scrollTop = messages.scrollHeight;
        }
    </script>
</body>
</html>'''

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

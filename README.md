# RAG Marakame - Déploiement Railway

## Étapes de déploiement

### 1. Créer un repo GitHub
- Allez sur github.com/new
- Nom: `rag-marakame`
- Cochez "Add a README"
- Créez le repo

### 2. Uploader les fichiers
- Cliquez sur "Add file" > "Upload files"
- Glissez les 3 fichiers: `main.py`, `requirements.txt`, `Procfile`
- Commit

### 3. Déployer sur Railway
- Allez sur railway.app
- "New Project" > "Deploy from GitHub repo"
- Sélectionnez votre repo `rag-marakame`
- Railway détecte automatiquement Python

### 4. Ajouter la clé API
- Dans Railway, cliquez sur votre service
- Onglet "Variables"
- Ajoutez: `ANTHROPIC_API_KEY` = votre clé sk-ant-...

### 5. Tester
Votre API sera disponible sur une URL comme:
`https://rag-marakame-production.up.railway.app`

Testez avec:
```bash
curl -X POST https://VOTRE-URL/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Quels sont les délais de livraison?"}'
```

## Endpoints

- `GET /` - Info API
- `GET /health` - Status
- `POST /search` - Recherche FAQ (body: `{"query": "..."}`)
- `POST /chat` - Chat avec Claude (body: `{"message": "..."}`)

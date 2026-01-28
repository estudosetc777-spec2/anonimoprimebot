# AnonimoPrimeBot Automático (Starter)

✅ Bot do Telegram (polling) + FastAPI  
✅ Botões Mensal/Anual com links de checkout  
✅ Link de convite (1 uso) quando o pedido estiver marcado como PAGO  
✅ Endpoint `/syncpay/webhook` preparado para evoluir a automação

## Variáveis de ambiente
- BOT_TOKEN
- GROUP_CHAT_ID  (id do grupo VIP, ex: -1001234567890)
- MENSAL_URL
- ANUAL_URL
- SYNC_CLIENT_ID
- SYNC_CLIENT_SECRET
- SYNC_WEBHOOK_SECRET

## Rodar local (Windows)
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

set BOT_TOKEN=...
set GROUP_CHAT_ID=...
set MENSAL_URL=...
set ANUAL_URL=...
set SYNC_WEBHOOK_SECRET=...

uvicorn main:app --host 0.0.0.0 --port 8000
Abra http://localhost:8000/health

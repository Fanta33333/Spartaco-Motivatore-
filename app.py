import os
import logging
import time
from openai import OpenAI
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Configurazione Iniziale ---
# Carica le variabili d'ambiente da un file .env se presente (per lo sviluppo locale)
load_dotenv() 

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

# Controlla che le variabili d'ambiente siano state caricate correttamente
if not all([TELEGRAM_TOKEN, OPENAI_API_KEY, ASSISTANT_ID]):
    # Se il codice è in produzione, le variabili devono esistere. Se mancano, il bot si ferma.
    logging.critical("ERRORE CRITICO: Mancano una o più variabili d'ambiente (TELEGRAM_TOKEN, OPENAI_API_KEY, ASSISTANT_ID)")
    # Usiamo 'raise' per fermare l'esecuzione se mancano le chiavi
    raise ValueError("ERRORE CRITICO: Mancano una o più variabili d'ambiente.")

# Inizializza il client OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# Dizionario per memorizzare le conversazioni (thread) per ogni utente
# NOTA: Questo dizionario si resetta ogni volta che il bot si riavvia.
# Per una soluzione persistente, sarebbe necessario un database.
user_threads = {}

# Configura il logging per mostrare informazioni utili
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)

# --- Funzioni del Bot ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /start, creando un nuovo thread per l'utente."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    try:
        # Crea un nuovo thread di conversazione per l'utente su OpenAI
        thread = client.beta.threads.create()
        user_threads[chat_id] = thread.id
        logging.info(f"Creato nuovo thread {thread.id} per l'utente {chat_id}")
        await update.message.reply_html(
            f"Ciao {user.mention_html()}! 👋\n\nSono pronto a parlare con te. Scrivimi qualcosa.",
        )
    except Exception as e:
        logging.error(f"Errore nella creazione del thread per {chat_id}: {e}")
        await update.message.reply_text("Scusa, non riesco a inizializzare la nostra conversazione. Riprova più tardi.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce tutti i messaggi di testo degli utenti."""
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    # MODIFICA 1: Se l'utente non ha un thread (magari il bot si è riavviato),
    # esegue la funzione 'start' per crearne uno prima di continuare.
    if chat_id not in user_threads:
        logging.warning(f"Thread non trovato per l'utente {chat_id}. Eseguo /start per crearne uno nuovo.")
        await start(update, context)
        # Non eseguiamo il resto della funzione, perché il messaggio di benvenuto è già la risposta.
        return

    thread_id = user_threads[chat_id]
    logging.info(f"Messaggio ricevuto nel thread {thread_id} dall'utente {chat_id}: '{user_text}'")
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')

    try:
        # 1. Aggiungi il messaggio dell'utente al thread
        client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_text)

        # 2. Esegui l'assistente su quel thread
        run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=ASSISTANT_ID)

        # 3. Aspetta che l'assistente abbia finito di elaborare
        while run.status in ["queued", "in_progress"]:
            time.sleep(1) # Riduciamo il polling per essere più gentili con l'API
            run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)

        # Controlla se l'esecuzione è fallita
        if run.status == "failed":
            logging.error(f"L'esecuzione del thread {thread_id} è fallita: {run.last_error.message}")
            raise Exception("L'assistente non è riuscito a completare la richiesta.")
        
        # 4. Recupera i messaggi dal thread
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        
        # 5. Estrai l'ultima risposta dell'assistente e inviala
        assistant_response = messages.data[0].content[0].text.value
        await update.message.reply_text(assistant_response)

    except Exception as e:
        logging.error(f"Errore durante la gestione del messaggio per il thread {thread_id}: {e}")
        await update.message.reply_text("Ops, qualcosa è andato storto. Ho informato i miei creatori!")

# --- Funzione Principale ---

def main() -> None:
    """Avvia il bot e lo mette in ascolto."""
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("Bot avviato con successo! In ascolto...")
    
    # MODIFICA 2: Aggiunto 'drop_pending_updates=True' per ignorare i vecchi messaggi
    # ricevuti mentre il bot era offline. Molto utile in produzione.
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

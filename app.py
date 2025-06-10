import os
import logging
import time
from openai import OpenAI
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Configurazione Iniziale ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

if not all([TELEGRAM_TOKEN, OPENAI_API_KEY, ASSISTANT_ID]):
    raise ValueError("Errore: mancano uno o più token/ID nel file .env (TELEGRAM_TOKEN, OPENAI_API_KEY, ASSISTANT_ID)")

client = OpenAI(api_key=OPENAI_API_KEY)

# Dizionario per memorizzare le conversazioni (thread) per ogni utente
user_threads = {}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- Funzioni del Bot ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    try:
        thread = client.beta.threads.create()
        user_threads[chat_id] = thread.id
        logging.info(f"Creato nuovo thread {thread.id} per l'utente {chat_id}")
        await update.message.reply_html(
            f"Ciao {user.mention_html()}! 👋\n\nSono pronto a parlare con te. Usa lo stile e le conoscenze con cui sono stato creato.",
        )
    except Exception as e:
        logging.error(f"Errore nella creazione del thread per {chat_id}: {e}")
        await update.message.reply_text("Scusa, non riesco a inizializzare la nostra conversazione. Riprova più tardi.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    if chat_id not in user_threads:
        # Se l'utente non ha un thread, lo invita a usare /start
        await start(update, context)
        return

    thread_id = user_threads[chat_id]
    logging.info(f"Messaggio ricevuto nel thread {thread_id} dall'utente {chat_id}: '{user_text}'")
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')

    try:
        # 1. Aggiungi il messaggio dell'utente al thread
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_text
        )

        # 2. Esegui l'assistente su quel thread
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID
        )

        # 3. Aspetta che l'assistente abbia finito di elaborare la risposta
        while run.status != "completed":
            time.sleep(0.5)
            run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            if run.status == "failed":
                raise Exception(f"L'esecuzione dell'assistente è fallita: {run.last_error.message}")

        # 4. Recupera tutti i messaggi del thread
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        
        # 5. Estrai l'ultima risposta dell'assistente e inviala
        assistant_response = messages.data[0].content[0].text.value
        await update.message.reply_text(assistant_response)

    except Exception as e:
        logging.error(f"Errore durante la gestione del messaggio per il thread {thread_id}: {e}")
        await update.message.reply_text("Ops, qualcosa è andato storto mentre elaboravo la tua richiesta.")

# --- Funzione Principale (con la sintassi corretta per pulire i vecchi messaggi) ---

def main() -> None:
    """Avvia il bot e lo mette in ascolto."""
    
    # Crea un'istanza del builder
    builder = Application.builder().token(TELEGRAM_TOKEN)
    
    # Imposta la funzione per pulire i vecchi aggiornamenti prima di iniziare
    async def post_init(application: Application) -> None:
        await application.bot.get_updates(drop_pending_updates=True)

    builder.post_init(post_init)
    
    # Costruisci l'applicazione
    application = builder.build()

    # Aggiungi i gestori dei comandi e dei messaggi
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("Bot avviato con successo! In ascolto...")
    
    # Avvia il bot
    application.run_polling()

if __name__ == '__main__':
    main()

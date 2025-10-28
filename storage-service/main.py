import os
import time
from fastapi import FastAPI, Request, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv
import json
import threading
try:
    from kafka import KafkaConsumer
except Exception:
    KafkaConsumer = None

load_dotenv()

# --- Configuración de la Base de Datos ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/yahoo_db")
MAX_RETRIES = int(os.getenv("DB_MAX_RETRIES", 10))
RETRY_DELAY = int(os.getenv("DB_RETRY_DELAY", 5))
# Configuración Kafka
KAFKA_ENABLED = os.getenv("KAFKA_ENABLED", "true").lower() == "true"
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
VALIDATED_TOPIC = os.getenv("VALIDATED_TOPIC", "validated-responses")
STORAGE_CONSUMER_GROUP = os.getenv("STORAGE_CONSUMER_GROUP", "storage-service")

engine = None
for i in range(MAX_RETRIES):
    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("Conexión a la base de datos establecida exitosamente.")
        break
    except OperationalError as e:
        print(f"Intento {i+1}/{MAX_RETRIES}: No se pudo conectar a la base de datos. Reintentando en {RETRY_DELAY}s...")
        print(f"Error: {e}")
        time.sleep(RETRY_DELAY)
else:
    print("Error crítico: No se pudo conectar a la base de datos después de varios intentos.")
    raise SystemExit(1)

app = FastAPI(title="Storage Service")

# --- Helpers DB ---
def insert_response(payload: dict):
    stmt = text(
        """
        INSERT INTO responses (question, original_answer, llm_answer, score)
        VALUES (:question, :original_answer, :llm_answer, :score)
        ON CONFLICT (question) DO UPDATE SET
            original_answer = EXCLUDED.original_answer,
            llm_answer = EXCLUDED.llm_answer,
            score = EXCLUDED.score,
            updated_at = CURRENT_TIMESTAMP;
        """
    )
    with engine.begin() as connection:
        connection.execute(stmt, payload)

# --- Kafka Consumer (validated-responses) ---
def _kafka_consumer_loop():
    if not KafkaConsumer:
        print("kafka-python no está disponible; consumidor Kafka deshabilitado.")
        return
    
    # Retry logic para conectar a Kafka
    max_retries = 10
    retry_delay = 5
    for attempt in range(max_retries):
        try:
            print(f"Storage Service: Intentando conectar a Kafka (intento {attempt + 1}/{max_retries})...")
            consumer = KafkaConsumer(
                VALIDATED_TOPIC,
                bootstrap_servers=KAFKA_BROKER,
                group_id=STORAGE_CONSUMER_GROUP,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                enable_auto_commit=True,
                auto_offset_reset='earliest'
            )
            print(f"Storage Service: Consumidor Kafka conectado exitosamente a '{VALIDATED_TOPIC}' en {KAFKA_BROKER}")
            break
        except Exception as e:
            print(f"Storage Service: Error conectando a Kafka (intento {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"Storage Service: Reintentando en {retry_delay} segundos...")
                time.sleep(retry_delay)
            else:
                print("Storage Service: No se pudo conectar a Kafka después de múltiples intentos.")
                return
    
    try:
        for message in consumer:
            payload = message.value
            question = payload.get("question")
            if not question:
                print("Mensaje inválido recibido en validated-responses: falta 'question'")
                continue
            try:
                insert_response(payload)
                print(f"Persistido desde Kafka: '{question[:80]}...' score={payload.get('score')}")
            except Exception as e:
                print(f"Error al persistir mensaje Kafka: {e}")
    except Exception as e:
        print(f"Error en loop consumidor Kafka: {e}")

def start_kafka_consumer_async():
    if KAFKA_ENABLED:
        t = threading.Thread(target=_kafka_consumer_loop, daemon=True)
        t.start()
    else:
        print("Kafka consumer deshabilitado por configuración.")

# Iniciar consumidor Kafka en background
start_kafka_consumer_async()

@app.post("/storage")
async def store_response(request: Request):
    payload = await request.json()
    question = payload.get("question")
    if not question:
        raise HTTPException(status_code=400, detail="'question' es obligatoria")

    try:
        insert_response(payload)
        print(f"Dato guardado para la pregunta: '{question[:80]}...'")
        return {"status": "success", "message": "Datos almacenados correctamente."}
    except Exception as e:
        print(f"Error al guardar en la base de datos: {e}")
        raise HTTPException(status_code=500, detail="Error al interactuar con la base de datos.")

@app.get("/lookup")
async def lookup_response(question: str):
    if not question:
        raise HTTPException(status_code=400, detail="'question' es obligatoria")
    stmt = text(
        """
        SELECT question, original_answer, llm_answer, score, hit_count, created_at
        FROM responses
        WHERE question = :question
        """
    )
    try:
        with engine.connect() as connection:
            result = connection.execute(stmt, {"question": question}).mappings().first()
        if result:
            return {"found": True, "data": dict(result)}
        else:
            return {"found": False}
    except Exception as e:
        print(f"Error en lookup: {e}")
        raise HTTPException(status_code=500, detail="Error al consultar la base de datos.")

@app.post("/hit")
async def register_hit(request: Request):
    payload = await request.json()
    question = payload.get("question")
    if not question:
        raise HTTPException(status_code=400, detail="'question' es obligatoria")

    stmt = text(
        """
        UPDATE responses
        SET hit_count = hit_count + 1
        WHERE question = :question;
        """
    )

    try:
        with engine.begin() as connection:
            result = connection.execute(stmt, {"question": question})
        print(f"HIT registrado para la pregunta: '{question[:80]}...'")
        return {"status": "success", "message": "Hit registrado."}
    except Exception as e:
        print(f"Error al registrar hit: {e}")
        raise HTTPException(status_code=500, detail="Error al actualizar el contador de hits.")

@app.get("/")
async def root():
    return {"message": "Storage Service está funcionando y conectado a la base de datos."}

@app.get("/health")
async def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

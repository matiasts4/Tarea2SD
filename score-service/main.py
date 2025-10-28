import os
from fastapi import FastAPI, Request, HTTPException
from sentence_transformers import SentenceTransformer, util
import google.generativeai as genai
import requests
from dotenv import load_dotenv
import json
import threading
import time
try:
    from kafka import KafkaConsumer, KafkaProducer
except Exception:
    KafkaConsumer = None
    KafkaProducer = None

# Cargar variables desde .env si existe
load_dotenv()

# --- Configuración ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("La variable de entorno GEMINI_API_KEY no ha sido configurada.")

genai.configure(api_key=GEMINI_API_KEY)

STORAGE_SERVICE_URL = os.getenv("STORAGE_SERVICE_URL", "http://localhost:8003/storage")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash-lite")

# Kafka config
KAFKA_ENABLED = os.getenv("KAFKA_ENABLED", "true").lower() == "true"
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
REQUESTS_TOPIC = os.getenv("REQUESTS_TOPIC", "questions")
GENERATED_TOPIC = os.getenv("GENERATED_TOPIC", "generated")
ERRORS_TOPIC = os.getenv("ERRORS_TOPIC", "errors")
SCORE_CONSUMER_GROUP = os.getenv("SCORE_CONSUMER_GROUP", "score-service")
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", 3))

print("Cargando el modelo de similitud de sentencias (puede tardar)...")
similarity_model = SentenceTransformer('all-MiniLM-L6-v2')
print("Modelo de similitud cargado.")

# Intentar inicializar el modelo generativo
try:
    llm = genai.GenerativeModel(GEMINI_MODEL_NAME)
except Exception as e:
    raise RuntimeError(f"No se pudo inicializar el modelo Gemini '{GEMINI_MODEL_NAME}': {e}")

app = FastAPI(title="Score Service")

_producer = None

def _get_producer():
    global _producer
    if _producer is None and KafkaProducer:
        try:
            _producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
            print(f"Score Service: Kafka producer conectado a {KAFKA_BROKER}")
        except Exception as e:
            print(f"No se pudo crear KafkaProducer: {e}")
            _producer = None
    return _producer


def get_llm_answer(question: str) -> str:
    """Envía la pregunta a la API de Gemini y retorna la respuesta generada."""
    try:
        prompt = f"Responde la siguiente pregunta de la forma más clara y concisa posible: {question}"
        response = llm.generate_content(prompt)
        return getattr(response, 'text', 'Sin texto devuelto por LLM')
    except Exception as e:
        print(f"Error al contactar la API de Gemini: {e}")
        return None


def calculate_similarity(text1: str, text2: str) -> float:
    """Calcula similitud de coseno entre dos textos usando embeddings."""
    embedding1 = similarity_model.encode(text1, convert_to_tensor=True)
    embedding2 = similarity_model.encode(text2, convert_to_tensor=True)
    cosine_score = util.pytorch_cos_sim(embedding1, embedding2)
    return cosine_score.item()


def _process_question(question: str, original_answer: str, attempts: int = 0):
    print(f"Procesando (Kafka) pregunta: '{question[:80]}...' (attempts={attempts})")
    llm_answer = get_llm_answer(question)
    prod = _get_producer()
    if llm_answer is None:
        err_msg = {
            "question": question,
            "original_answer": original_answer,
            "attempts": attempts,
            "error": "llm_generation_failed",
            "ts": time.time()
        }
        if prod:
            try:
                prod.send(ERRORS_TOPIC, err_msg)
                prod.flush()
            except Exception as e:
                print(f"Error produciendo a {ERRORS_TOPIC}: {e}")
        # reintentar si aplica
        if attempts + 1 <= MAX_ATTEMPTS and prod:
            requeue = {
                "question": question,
                "original_answer": original_answer,
                "attempts": attempts + 1,
                "enqueued_at": time.time()
            }
            try:
                prod.send(REQUESTS_TOPIC, requeue)
                prod.flush()
                print("Reencolada pregunta por fallo LLM.")
            except Exception as e:
                print(f"Error reencolando en {REQUESTS_TOPIC}: {e}")
        return

    # Producir respuesta generada (sin score; Flink lo calculará)
    msg = {
        "question": question,
        "original_answer": original_answer,
        "llm_answer": llm_answer,
        "attempts": attempts,
        "generated_at": time.time()
    }
    if prod:
        try:
            prod.send(GENERATED_TOPIC, msg)
            prod.flush()
            print("Producida respuesta generada en Kafka.")
        except Exception as e:
            print(f"Error enviando a {GENERATED_TOPIC}: {e}")


def _kafka_consumer_loop():
    if not KafkaConsumer:
        print("kafka-python no disponible; score-service consumidor deshabilitado.")
        return
    
    # Retry logic para conectar a Kafka
    max_retries = 10
    retry_delay = 5
    for attempt in range(max_retries):
        try:
            print(f"Score Service: Intentando conectar a Kafka (intento {attempt + 1}/{max_retries})...")
            consumer = KafkaConsumer(
                REQUESTS_TOPIC,
                bootstrap_servers=KAFKA_BROKER,
                group_id=SCORE_CONSUMER_GROUP,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                enable_auto_commit=True,
                auto_offset_reset='earliest'
            )
            print(f"Score Service: Consumidor Kafka conectado exitosamente a '{REQUESTS_TOPIC}' en {KAFKA_BROKER}")
            break
        except Exception as e:
            print(f"Score Service: Error conectando a Kafka (intento {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"Score Service: Reintentando en {retry_delay} segundos...")
                time.sleep(retry_delay)
            else:
                print("Score Service: No se pudo conectar a Kafka después de múltiples intentos.")
                return
    
    try:
        for msg in consumer:
            payload = msg.value
            question = payload.get("question")
            original_answer = payload.get("original_answer")
            attempts = int(payload.get("attempts", 0) or 0)
            if not question or original_answer is None:
                print("Mensaje inválido en questions: falta 'question' u 'original_answer'")
                continue
            try:
                _process_question(question, original_answer, attempts)
            except Exception as e:
                print(f"Error procesando mensaje Kafka: {e}")
    except Exception as e:
        print(f"Error en loop consumidor Kafka: {e}")


def start_kafka_consumer_async():
    if KAFKA_ENABLED:
        t = threading.Thread(target=_kafka_consumer_loop, daemon=True)
        t.start()
    else:
        print("Kafka en score-service deshabilitado por configuración.")

# Iniciar consumidor Kafka en background
start_kafka_consumer_async()

@app.post("/score")
async def handle_scoring(request: Request):
    """Recibe pregunta y respuesta original, genera respuesta LLM y calcula score."""
    try:
        payload = await request.json()
        question = payload.get("question")
        original_answer = payload.get("original_answer")

        if not all([question, original_answer]):
            raise HTTPException(status_code=400, detail="Faltan 'question' u 'original_answer'.")

        print(f"\nRecibida pregunta para scoring: '{question[:80]}...' (HTTP)")
        print("Generando respuesta con el LLM...")
        llm_answer = get_llm_answer(question) or ""
        print(f"Respuesta del LLM (truncada): '{llm_answer[:80]}...'")

        print("Calculando score de similitud...")
        score = calculate_similarity(original_answer, llm_answer)
        print(f"Score de similitud: {score:.4f}")

        result_payload = {
            "question": question,
            "original_answer": original_answer,
            "llm_answer": llm_answer,
            "score": score
        }

        # Enviar al storage service (modo Tarea 1)
        try:
            storage_response = requests.post(STORAGE_SERVICE_URL, json=result_payload, timeout=5)
            storage_response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error: No se pudo conectar con el Storage Service. {e}")
            raise HTTPException(status_code=503, detail="El servicio de almacenamiento no está disponible.")

        return result_payload

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error procesando la petición de scoring: {e}")
        raise HTTPException(status_code=500, detail="Error interno en el servidor de score.")


@app.get("/")
def read_root():
    return {"message": "Score Service está funcionando correctamente."}

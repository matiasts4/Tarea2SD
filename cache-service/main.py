import os
from fastapi import FastAPI, Request, HTTPException
import requests
from collections import OrderedDict, deque
import time
import json

# Añadir importación segura de KafkaProducer
try:
    from kafka import KafkaProducer
except Exception:
    KafkaProducer = None

# --- Configuración ---
SCORE_SERVICE_URL = os.getenv("SCORE_SERVICE_URL", "http://localhost:8002/score")
# Base URL del storage (sin sufijo /storage). El endpoint /hit y /storage se añaden explícitamente.
STORAGE_SERVICE_URL = os.getenv("STORAGE_SERVICE_URL", "http://localhost:8003")

CACHE_SIZE = int(os.getenv("CACHE_SIZE", 1000))  # Tamaño máximo de la caché
CACHE_POLICY = os.getenv("CACHE_POLICY", "LRU")  # Política de desalojo: LRU, FIFO, LFU
CACHE_TTL = int(os.getenv("CACHE_TTL", 0))  # TTL en segundos (0 = sin expiración)
PIPELINE_MODE = os.getenv("PIPELINE_MODE", "async").lower()  # 'async' o 'sync'
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
REQUESTS_TOPIC = os.getenv("REQUESTS_TOPIC", "questions")

# --- Implementación de Múltiples Políticas de Caché ---
class CacheManager:
    def __init__(self, size, policy, ttl=0):
        self.size = size
        self.policy = policy.upper()
        self.ttl = ttl  # Time To Live en segundos (0 = sin expiración)
        self.stats = {"hits": 0, "misses": 0, "evictions": 0, "expirations": 0}
        self.timestamps = {}  # Almacena el timestamp de inserción de cada key
        
        if self.policy == "LRU":
            self.cache = OrderedDict()
        elif self.policy == "FIFO":
            self.cache = {}
            self.insertion_order = deque()
        elif self.policy == "LFU":
            self.cache = {}
            self.frequencies = {}
            self.freq_groups = {}  # frequency -> set of keys
            self.min_freq = 0
        else:
            raise ValueError(f"Política de caché no soportada: {policy}")
    
    def _is_expired(self, key):
        """Verifica si una entrada ha expirado según el TTL."""
        if self.ttl == 0:  # Sin expiración
            return False
        
        if key not in self.timestamps:
            return True
        
        elapsed = time.time() - self.timestamps[key]
        return elapsed > self.ttl
    
    def _remove_expired(self, key):
        """Elimina una entrada expirada."""
        if key in self.cache:
            del self.cache[key]
        if key in self.timestamps:
            del self.timestamps[key]
        
        if self.policy == "FIFO":
            if key in self.insertion_order:
                self.insertion_order.remove(key)
        elif self.policy == "LFU":
            if key in self.frequencies:
                freq = self.frequencies[key]
                if freq in self.freq_groups and key in self.freq_groups[freq]:
                    self.freq_groups[freq].remove(key)
                    if not self.freq_groups[freq]:
                        del self.freq_groups[freq]
                del self.frequencies[key]
        
        self.stats["expirations"] += 1
        print(f"Entrada expirada por TTL: '{key[:80]}...'")
    
    def get(self, key):
        """Obtiene un valor de la caché según la política configurada."""
        if key not in self.cache:
            self.stats["misses"] += 1
            return None
        
        # Verificar si ha expirado
        if self._is_expired(key):
            self._remove_expired(key)
            self.stats["misses"] += 1
            return None
        
        self.stats["hits"] += 1
        
        if self.policy == "LRU":
            # Mover al final (más reciente)
            self.cache.move_to_end(key)
        elif self.policy == "LFU":
            # Incrementar frecuencia
            self._increment_frequency(key)
        # FIFO no necesita actualización en get
        
        return self.cache[key]
    
    def put(self, key, value):
        """Inserta/actualiza un valor en la caché según la política configurada."""
        # Si la entrada existe, verificar si ha expirado
        if key in self.cache and self._is_expired(key):
            self._remove_expired(key)
        
        if key in self.cache:
            # Actualizar valor existente
            self.cache[key] = value
            self.timestamps[key] = time.time()  # Actualizar timestamp
            if self.policy == "LRU":
                self.cache.move_to_end(key)
            elif self.policy == "LFU":
                self._increment_frequency(key)
            return
        
        # Nuevo elemento
        if len(self.cache) >= self.size:
            self._evict()
        
        self.cache[key] = value
        self.timestamps[key] = time.time()  # Guardar timestamp de inserción
        
        if self.policy == "FIFO":
            self.insertion_order.append(key)
        elif self.policy == "LFU":
            self.frequencies[key] = 1
            if 1 not in self.freq_groups:
                self.freq_groups[1] = set()
            self.freq_groups[1].add(key)
            self.min_freq = 1
    
    def _evict(self):
        """Elimina un elemento según la política configurada."""
        self.stats["evictions"] += 1
        
        if self.policy == "LRU":
            evicted_key, _ = self.cache.popitem(last=False)
        elif self.policy == "FIFO":
            evicted_key = self.insertion_order.popleft()
            del self.cache[evicted_key]
        elif self.policy == "LFU":
            # Encontrar y eliminar elemento con menor frecuencia
            evicted_key = next(iter(self.freq_groups[self.min_freq]))
            if not self.freq_groups[self.min_freq]:
                del self.freq_groups[self.min_freq]
            del self.frequencies[evicted_key]
            del self.cache[evicted_key]
        
        # Eliminar timestamp
        if evicted_key in self.timestamps:
            del self.timestamps[evicted_key]
        
        print(f"Caché llena. Evicción {self.policy}: '{evicted_key[:80]}...'")
    
    def _increment_frequency(self, key):
        """Incrementa la frecuencia de un elemento (solo para LFU)."""
        old_freq = self.frequencies[key]
        new_freq = old_freq + 1
        # Remover de grupo de frecuencia anterior
        self.freq_groups[old_freq].remove(key)
        if not self.freq_groups[old_freq] and old_freq == self.min_freq:
            self.min_freq += 1
        
        # Agregar a nuevo grupo de frecuencia
        self.frequencies[key] = new_freq
        if new_freq not in self.freq_groups:
            self.freq_groups[new_freq] = set()
        self.freq_groups[new_freq].add(key)
    
    def get_stats(self):
        """Retorna estadísticas del caché."""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "size": len(self.cache),
            "capacity": self.size,
            "policy": self.policy,
            "ttl": self.ttl,
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "evictions": self.stats["evictions"],
            "expirations": self.stats["expirations"],
            "hit_rate": round(hit_rate, 2)
        }

# Inicializar el gestor de caché
cache_manager = CacheManager(CACHE_SIZE, CACHE_POLICY, CACHE_TTL)
app = FastAPI(title="Cache Service")

_kafka_producer = None

def _get_producer():
    global _kafka_producer
    if _kafka_producer is None and KafkaProducer:
        try:
            _kafka_producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
            print(f"Cache Service: Kafka producer conectado a {KAFKA_BROKER}")
        except Exception as e:
            print(f"No se pudo crear KafkaProducer: {e}")
            _kafka_producer = None
    return _kafka_producer


def cache_put(question: str, value):
    """Inserta/actualiza un valor en la caché."""
    cache_manager.put(question, value)


def cache_get(question: str):
    """Obtiene un valor de la caché."""
    return cache_manager.get(question)


@app.post("/query")
async def handle_query(request: Request):
    """
    Endpoint principal que recibe las preguntas del generador de tráfico.
    Tarea 2: Primero consulta el almacenamiento; si no existe, encola la pregunta en Kafka.
    """
    try:
        payload = await request.json()
        question = payload.get("question")
        original_answer = payload.get("original_answer")

        if not question:
            raise HTTPException(status_code=400, detail="La clave 'question' es obligatoria.")

        print(f"\nRecibida pregunta: '{question[:80]}...'")

        # 1) Consultar almacenamiento primero
        try:
            lookup = requests.get(f"{STORAGE_SERVICE_URL}/lookup", params={"question": question}, timeout=5)
            if lookup.status_code == 200:
                data = lookup.json()
                if data.get("found"):
                    print("-> Storage HIT: respuesta existente encontrada.")
                    cache_put(question, data["data"])  # opcional: popular caché
                    try:
                        requests.post(f"{STORAGE_SERVICE_URL}/hit", json={"question": question}, timeout=2)
                    except requests.RequestException as e:
                        print(f"Advertencia: No se pudo notificar el HIT al Storage Service. {e}")
                    return {"status": "hit", "message": "Respuesta obtenida desde almacenamiento.", "data": data["data"]}
            else:
                print(f"Lookup storage devolvió {lookup.status_code}: {lookup.text}")
        except requests.RequestException as e:
            print(f"Advertencia: fallo consultando almacenamiento: {e}")

        # 2) Consultar caché (por compatibilidad)
        cached_value = cache_get(question)
        if cached_value is not None:
            print("-> Cache HIT para la pregunta.")
            try:
                requests.post(f"{STORAGE_SERVICE_URL}/hit", json={"question": question}, timeout=2)
            except requests.RequestException as e:
                print(f"Advertencia: No se pudo notificar el HIT al Storage Service. {e}")
            return {"status": "hit", "message": "Respuesta obtenida desde la caché.", "data": cached_value}

        # 3) Miss: Async pipeline o fallback sync
        if PIPELINE_MODE == "async":
            producer = _get_producer()
            if not producer:
                raise HTTPException(status_code=503, detail="Kafka no está disponible para encolar la pregunta.")
            msg = {
                "question": question,
                "original_answer": original_answer,
                "attempts": 0,
                "enqueued_at": time.time()
            }
            try:
                producer.send(REQUESTS_TOPIC, msg)
                producer.flush()
                print("-> Cache MISS. Pregunta encolada en Kafka para procesamiento asíncrono.")
                return {"status": "queued", "message": "Pregunta encolada para procesamiento asíncrono."}
            except Exception as e:
                print(f"Error enviando a Kafka: {e}")
                raise HTTPException(status_code=503, detail="No se pudo encolar la pregunta en Kafka.")
        else:
            # Fallback Tarea 1 (sincrónico)
            print("-> Cache MISS. Enviando al Score Service (modo sync)...")
            try:
                response_from_score = requests.post(SCORE_SERVICE_URL, json=payload, timeout=15)
                response_from_score.raise_for_status()
                score_data = response_from_score.json()
                cache_put(question, score_data)
                return {"status": "miss", "data_from_score": score_data}
            except requests.RequestException as e:
                print(f"Error: No se pudo conectar con el Score Service. {e}")
                raise HTTPException(status_code=503, detail="El servicio de puntuación no está disponible.")

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error procesando la petición: {e}")
        raise HTTPException(status_code=500, detail="Error interno en el servidor de caché.")


@app.get("/")
def read_root():
    stats = cache_manager.get_stats()
    return {"message": "Cache Service está funcionando correctamente.", "cache_size": stats["size"]}


@app.get("/stats")
def cache_stats():
    """Devuelve estadísticas completas de la caché incluyendo rendimiento."""
    return cache_manager.get_stats()

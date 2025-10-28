#!/usr/bin/env python3
"""
Quality Processor using kafka-python
Validates response quality and implements feedback loop
"""
import os
import json
import time
import logging
from kafka import KafkaConsumer, KafkaProducer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
GENERATED_TOPIC = os.getenv("GENERATED_TOPIC", "generated")
VALIDATED_TOPIC = os.getenv("VALIDATED_TOPIC", "validated-responses")
REQUESTS_TOPIC = os.getenv("REQUESTS_TOPIC", "questions")
QUALITY_THRESHOLD = float(os.getenv("QUALITY_THRESHOLD", "0.5"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))

def calculate_quality_score(original: str, generated: str) -> float:
    """
    Calculate quality score with lenient criteria:
    - Basic completeness check (not empty, reasonable length)
    - Semantic relevance (some keyword overlap)
    - Adjusted for cross-language responses
    """
    if not original or not generated:
        return 0.0
    
    # Normalize texts
    orig_words = set(original.lower().split())
    gen_words = set(generated.lower().split())
    
    # 1. Completeness check (40% weight)
    # Generated answer should have reasonable length (at least 3 words)
    if len(gen_words) < 3:
        completeness = 0.0
    elif len(gen_words) >= 5:
        completeness = 1.0
    else:
        completeness = len(gen_words) / 5.0
    
    # 2. Keyword overlap (30% weight) - very lenient
    # Filter out common stop words
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'is', 'was', 'are', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should'}
    key_words = orig_words - stop_words
    
    if key_words and len(key_words) > 0:
        # Even 1 keyword match gives partial credit
        matches = len(key_words & gen_words)
        keyword_score = min(1.0, matches / max(1, len(key_words) * 0.3))  # Only need 30% match
    else:
        keyword_score = 0.7  # Neutral if no keywords (e.g., very short original)
    
    # 3. Length appropriateness (30% weight)
    # Don't penalize longer answers, only very short ones
    orig_len = len(original)
    gen_len = len(generated)
    
    if gen_len >= orig_len * 0.5:  # At least 50% of original length
        length_score = 1.0
    elif gen_len >= 20:  # Or at least 20 characters
        length_score = 0.8
    else:
        length_score = gen_len / 20.0
    
    # Weighted score
    score = (completeness * 0.4) + (keyword_score * 0.3) + (length_score * 0.3)
    
    return score

def connect_kafka_consumer(max_retries=10, retry_delay=5):
    """Connect to Kafka with retry logic"""
    for attempt in range(max_retries):
        try:
            logger.info(f"Conectando a Kafka (intento {attempt + 1}/{max_retries})...")
            consumer = KafkaConsumer(
                GENERATED_TOPIC,
                bootstrap_servers=KAFKA_BROKER,
                group_id='quality-processor',
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                auto_offset_reset='earliest',
                enable_auto_commit=True
            )
            logger.info(f"✓ Conectado a Kafka topic '{GENERATED_TOPIC}'")
            return consumer
        except Exception as e:
            logger.error(f"Error conectando a Kafka: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Reintentando en {retry_delay} segundos...")
                time.sleep(retry_delay)
            else:
                raise

def connect_kafka_producer(max_retries=10, retry_delay=5):
    """Connect to Kafka producer with retry logic"""
    for attempt in range(max_retries):
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            logger.info("✓ Kafka producer conectado")
            return producer
        except Exception as e:
            logger.error(f"Error conectando producer: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise

def main():
    logger.info("=== Quality Processor Iniciando ===")
    logger.info(f"Kafka Broker: {KAFKA_BROKER}")
    logger.info(f"Quality Threshold: {QUALITY_THRESHOLD}")
    logger.info(f"Max Attempts: {MAX_ATTEMPTS}")
    
    # Connect to Kafka
    consumer = connect_kafka_consumer()
    producer = connect_kafka_producer()
    
    logger.info("=== Procesando mensajes ===")
    processed_count = 0
    approved_count = 0
    rejected_count = 0
    
    try:
        for message in consumer:
            data = message.value
            question = data.get('question')
            original_answer = data.get('original_answer')
            llm_answer = data.get('llm_answer')
            attempts = data.get('attempts', 0)
            
            if not all([question, original_answer, llm_answer]):
                logger.warning("Mensaje incompleto, saltando...")
                continue
            
            # Calculate quality score
            score = calculate_quality_score(original_answer, llm_answer)
            processed_count += 1
            
            logger.info(f"[{processed_count}] Score: {score:.3f} | Attempts: {attempts} | Q: {question[:50]}...")
            
            if score >= QUALITY_THRESHOLD:
                # Approved - send to validated-responses
                validated_msg = {
                    'question': question,
                    'original_answer': original_answer,
                    'llm_answer': llm_answer,
                    'score': score,
                    'attempts': attempts,
                    'generated_at': data.get('generated_at'),
                    'validated_at': time.time()
                }
                producer.send(VALIDATED_TOPIC, validated_msg)
                producer.flush()
                approved_count += 1
                logger.info(f"  ✓ APROBADA (score >= {QUALITY_THRESHOLD})")
            
            elif attempts < MAX_ATTEMPTS:
                # Rejected - retry
                retry_msg = {
                    'question': question,
                    'original_answer': original_answer,
                    'attempts': attempts + 1,
                    'enqueued_at': time.time()
                }
                producer.send(REQUESTS_TOPIC, retry_msg)
                producer.flush()
                rejected_count += 1
                logger.info(f"  ✗ RECHAZADA - Reintento {attempts + 1}/{MAX_ATTEMPTS}")
            
            else:
                # Max attempts reached
                rejected_count += 1
                logger.warning(f"  ✗ RECHAZADA - Máximo de intentos alcanzado")
            
            # Log stats every 10 messages
            if processed_count % 10 == 0:
                logger.info(f"--- Stats: Procesados={processed_count}, Aprobados={approved_count}, Rechazados={rejected_count} ---")
    
    except KeyboardInterrupt:
        logger.info("Deteniendo procesador...")
    except Exception as e:
        logger.error(f"Error en procesamiento: {e}", exc_info=True)
    finally:
        consumer.close()
        producer.close()
        logger.info(f"=== Finalizado: {processed_count} mensajes procesados ===")

if __name__ == "__main__":
    main()

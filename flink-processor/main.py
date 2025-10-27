from pyflink.table import EnvironmentSettings, StreamTableEnvironment, DataTypes
from pyflink.table.udf import udf
import logging
import sys
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Environment variables
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
GENERATED_TOPIC = os.getenv("GENERATED_TOPIC", "generated")
VALIDATED_TOPIC = os.getenv("VALIDATED_TOPIC", "validated-responses")
REQUESTS_TOPIC = os.getenv("REQUESTS_TOPIC", "questions")
QUALITY_THRESHOLD = float(os.getenv("QUALITY_THRESHOLD", "0.5"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))

# UDF for quality score calculation (Jaccard similarity)
@udf(result_type=DataTypes.FLOAT())
def quality_score(original: str, generated: str) -> float:
    """Calculate Jaccard similarity between original and generated answers"""
    if not original or not generated:
        return 0.0
    
    # Convert to lowercase and split into words
    set_original = set(original.lower().split())
    set_generated = set(generated.lower().split())
    
    # Calculate Jaccard similarity
    intersection = len(set_original & set_generated)
    union = len(set_original | set_generated)
    
    if union == 0:
        return 0.0
    
    return float(intersection / union)

def main():
    try:
        logger.info("=== Iniciando Flink Quality Processor ===")
        logger.info(f"Kafka Broker: {KAFKA_BROKER}")
        logger.info(f"Quality Threshold: {QUALITY_THRESHOLD}")
        logger.info(f"Max Attempts: {MAX_ATTEMPTS}")
        
        # Create streaming environment
        env_settings = EnvironmentSettings.in_streaming_mode()
        t_env = StreamTableEnvironment.create(environment_settings=env_settings)
        
        # Register UDF
        t_env.create_temporary_function("quality_score", quality_score)
        logger.info("UDF 'quality_score' registrada exitosamente")
        
        # Create Kafka source table for generated responses
        logger.info(f"Creando tabla fuente: {GENERATED_TOPIC}")
        t_env.execute_sql(f"""
            CREATE TABLE generated_responses (
                question STRING,
                original_answer STRING,
                llm_answer STRING,
                attempts INT,
                generated_at DOUBLE,
                proc_time AS PROCTIME()
            ) WITH (
                'connector' = 'kafka',
                'topic' = '{GENERATED_TOPIC}',
                'properties.bootstrap.servers' = '{KAFKA_BROKER}',
                'properties.group.id' = 'flink-quality-processor',
                'scan.startup.mode' = 'earliest-offset',
                'format' = 'json'
            )
        """)
        
        # Create Kafka sink table for validated responses
        logger.info(f"Creando tabla destino: {VALIDATED_TOPIC}")
        t_env.execute_sql(f"""
            CREATE TABLE validated_responses (
                question STRING,
                original_answer STRING,
                llm_answer STRING,
                score FLOAT,
                attempts INT,
                generated_at DOUBLE,
                validated_at DOUBLE
            ) WITH (
                'connector' = 'kafka',
                'topic' = '{VALIDATED_TOPIC}',
                'properties.bootstrap.servers' = '{KAFKA_BROKER}',
                'format' = 'json'
            )
        """)
        
        # Create Kafka sink table for retry requests
        logger.info(f"Creando tabla destino para reintentos: {REQUESTS_TOPIC}")
        t_env.execute_sql(f"""
            CREATE TABLE retry_requests (
                question STRING,
                original_answer STRING,
                attempts INT,
                generated_at DOUBLE
            ) WITH (
                'connector' = 'kafka',
                'topic' = '{REQUESTS_TOPIC}',
                'properties.bootstrap.servers' = '{KAFKA_BROKER}',
                'format' = 'json'
            )
        """)
        
        # Create temporary view with quality scores
        logger.info("Creando vista temporal con scores de calidad...")
        t_env.execute_sql(f"""
            CREATE TEMPORARY VIEW scored_responses AS
            SELECT 
                question,
                original_answer,
                llm_answer,
                quality_score(original_answer, llm_answer) as score,
                attempts,
                generated_at,
                UNIX_TIMESTAMP() as validated_at
            FROM generated_responses
        """)
        
        # Insert validated responses (high quality)
        logger.info(f"Iniciando job de validación (threshold >= {QUALITY_THRESHOLD})...")
        validation_job = t_env.execute_sql(f"""
            INSERT INTO validated_responses
            SELECT 
                question,
                original_answer,
                llm_answer,
                score,
                attempts,
                generated_at,
                validated_at
            FROM scored_responses
            WHERE score >= {QUALITY_THRESHOLD}
        """)
        
        logger.info(f"Job de validación iniciado: {validation_job.get_job_client().get_job_id()}")
        
        # Insert retry requests (low quality, under max attempts)
        logger.info(f"Iniciando job de reintentos (threshold < {QUALITY_THRESHOLD}, attempts < {MAX_ATTEMPTS})...")
        retry_job = t_env.execute_sql(f"""
            INSERT INTO retry_requests
            SELECT 
                question,
                original_answer,
                attempts + 1 as attempts,
                generated_at
            FROM scored_responses
            WHERE score < {QUALITY_THRESHOLD} AND attempts < {MAX_ATTEMPTS}
        """)
        
        logger.info(f"Job de reintentos iniciado: {retry_job.get_job_client().get_job_id()}")
        
        logger.info("=== Flink Quality Processor en ejecución ===")
        logger.info("Esperando mensajes en el tópico 'generated'...")
        
        # Wait for jobs to complete (they run indefinitely in streaming mode)
        validation_job.wait()
        
    except Exception as e:
        logger.error(f"Error en Flink Quality Processor: {str(e)}")
        logger.error(f"Tipo de error: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Script para generar gráficos del análisis de la Tarea 2
Genera imágenes PNG que se incluirán en el informe LaTeX
"""
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from pathlib import Path

# Configurar estilo
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (10, 6)
plt.rcParams['font.size'] = 11
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['xtick.labelsize'] = 10
plt.rcParams['ytick.labelsize'] = 10
plt.rcParams['legend.fontsize'] = 10

# Crear directorio para gráficos
output_dir = Path("analysis/plots")
output_dir.mkdir(parents=True, exist_ok=True)

# ============================================================================
# GRÁFICO 1: Distribución de Scores de Calidad
# ============================================================================
def plot_score_distribution():
    """Histograma de distribución de scores con umbral marcado"""
    # Datos reales de la base de datos
    score_buckets = [-0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    counts = [3, 370, 2573, 3437, 2780, 2108, 1363, 872, 464, 264, 112, 28, 15]
    
    fig, ax = plt.subplots(figsize=(12, 7))
    
    # Crear barras
    bars = ax.bar(score_buckets, counts, width=0.08, alpha=0.7, 
                  color=['#d62728' if s < 0.6 else '#2ca02c' for s in score_buckets],
                  edgecolor='black', linewidth=0.5)
    
    # Línea vertical en el umbral
    ax.axvline(x=0.6, color='blue', linestyle='--', linewidth=2.5, 
               label='Umbral de Calidad (0.6)', zorder=5)
    
    # Anotaciones
    total_below = sum(counts[:9])  # scores < 0.6
    total_above = sum(counts[9:])   # scores >= 0.6
    total = sum(counts)
    
    ax.text(0.3, max(counts)*0.9, f'Rechazadas\n{total_below:,} ({total_below/total*100:.1f}%)',
            ha='center', va='top', fontsize=11, fontweight='bold',
            bbox=dict(boxstyle='round', facecolor='#ffcccc', alpha=0.8))
    
    ax.text(0.8, max(counts)*0.9, f'Aprobadas\n{total_above:,} ({total_above/total*100:.1f}%)',
            ha='center', va='top', fontsize=11, fontweight='bold',
            bbox=dict(boxstyle='round', facecolor='#ccffcc', alpha=0.8))
    
    ax.set_xlabel('Score de Calidad', fontweight='bold')
    ax.set_ylabel('Número de Respuestas', fontweight='bold')
    ax.set_title('Distribución de Scores de Calidad y Justificación del Umbral', 
                 fontweight='bold', pad=20)
    ax.legend(loc='upper right', framealpha=0.9)
    ax.grid(True, alpha=0.3)
    
    # Formato del eje Y
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))
    
    plt.tight_layout()
    plt.savefig(output_dir / 'distribucion_scores.png', dpi=300, bbox_inches='tight')
    print(f"✓ Generado: distribucion_scores.png")
    plt.close()

# ============================================================================
# GRÁFICO 2: Efectividad del Feedback Loop
# ============================================================================
def plot_feedback_effectiveness():
    """Gráfico de barras mostrando mejora por intento"""
    intentos = ['Primer\nIntento', 'Segundo\nIntento', 'Tercer\nIntento']
    scores = [0.700, 0.742, 0.781]
    aprobadas = [813, 156, 39]
    porcentajes = [80.7, 15.5, 3.8]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Subplot 1: Score promedio por intento
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c']
    bars1 = ax1.bar(intentos, scores, color=colors, alpha=0.8, edgecolor='black', linewidth=1)
    
    # Añadir valores sobre las barras
    for i, (bar, score) in enumerate(zip(bars1, scores)):
        height = bar.get_height()
        mejora = ((score - scores[0]) / scores[0] * 100) if i > 0 else 0
        label = f'{score:.3f}'
        if i > 0:
            label += f'\n(+{mejora:.1f}%)'
        ax1.text(bar.get_x() + bar.get_width()/2., height + 0.01,
                label, ha='center', va='bottom', fontweight='bold', fontsize=10)
    
    ax1.set_ylabel('Score Promedio', fontweight='bold')
    ax1.set_title('Mejora de Score por Intento', fontweight='bold', pad=15)
    ax1.set_ylim([0.65, 0.82])
    ax1.grid(True, alpha=0.3, axis='y')
    
    # Subplot 2: Respuestas aprobadas por intento
    bars2 = ax2.bar(intentos, aprobadas, color=colors, alpha=0.8, edgecolor='black', linewidth=1)
    
    # Añadir valores sobre las barras
    for bar, count, pct in zip(bars2, aprobadas, porcentajes):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 20,
                f'{count}\n({pct}%)', ha='center', va='bottom', 
                fontweight='bold', fontsize=10)
    
    ax2.set_ylabel('Respuestas Aprobadas', fontweight='bold')
    ax2.set_title('Distribución de Aprobaciones', fontweight='bold', pad=15)
    ax2.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_dir / 'efectividad_feedback.png', dpi=300, bbox_inches='tight')
    print(f"✓ Generado: efectividad_feedback.png")
    plt.close()

# ============================================================================
# GRÁFICO 3: Estrategia de Reintentos (Funnel Chart)
# ============================================================================
def plot_retry_funnel():
    """Gráfico de embudo mostrando recuperación por intento"""
    stages = ['Mensajes\nProcesados', 'Primer\nIntento', 'Segundo\nIntento', 'Tercer\nIntento', 'Recuperación\nTotal']
    values = [1008, 813, 156, 39, 1008]
    percentages = [100, 80.7, 15.5, 3.8, 100]
    colors_funnel = ['#3498db', '#2ecc71', '#f39c12', '#e74c3c', '#9b59b6']
    
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Crear barras horizontales
    y_pos = np.arange(len(stages))
    bars = ax.barh(y_pos, values, color=colors_funnel, alpha=0.8, 
                   edgecolor='black', linewidth=1.5)
    
    # Añadir valores y porcentajes
    for i, (bar, val, pct) in enumerate(zip(bars, values, percentages)):
        width = bar.get_width()
        label = f'{val:,} ({pct}%)'
        ax.text(width + 30, bar.get_y() + bar.get_height()/2.,
                label, ha='left', va='center', fontweight='bold', fontsize=11)
    
    ax.set_yticks(y_pos)
    ax.set_yticklabels(stages, fontweight='bold')
    ax.set_xlabel('Número de Mensajes', fontweight='bold')
    ax.set_title('Efectividad del Sistema de Reintentos - Recuperación 100%', 
                 fontweight='bold', pad=20, fontsize=14)
    ax.set_xlim([0, 1200])
    ax.grid(True, alpha=0.3, axis='x')
    
    # Invertir eje Y para efecto embudo
    ax.invert_yaxis()
    
    plt.tight_layout()
    plt.savefig(output_dir / 'embudo_reintentos.png', dpi=300, bbox_inches='tight')
    print(f"✓ Generado: embudo_reintentos.png")
    plt.close()

# ============================================================================
# GRÁFICO 4: Comparación Tarea 1 vs Tarea 2
# ============================================================================
def plot_architecture_comparison():
    """Comparación de métricas entre arquitecturas"""
    metrics = ['Latencia\n(cache hit)', 'Latencia\n(cache miss)', 'Concurrencia', 
               'Tolerancia\na Fallos', 'Pérdida\nde Datos']
    
    # Valores normalizados (0-10)
    tarea1 = [9, 6, 3, 2, 3]  # Síncrona
    tarea2 = [9, 4, 9, 9, 10]  # Asíncrona
    
    x = np.arange(len(metrics))
    width = 0.35
    
    fig, ax = plt.subplots(figsize=(12, 7))
    
    bars1 = ax.bar(x - width/2, tarea1, width, label='Tarea 1 (Síncrona)',
                   color='#e74c3c', alpha=0.8, edgecolor='black', linewidth=1)
    bars2 = ax.bar(x + width/2, tarea2, width, label='Tarea 2 (Asíncrona)',
                   color='#2ecc71', alpha=0.8, edgecolor='black', linewidth=1)
    
    # Añadir valores sobre las barras
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.2,
                   f'{int(height)}', ha='center', va='bottom', fontweight='bold')
    
    ax.set_ylabel('Rendimiento (0-10)', fontweight='bold')
    ax.set_title('Comparación Arquitectura Síncrona vs Asíncrona', 
                 fontweight='bold', pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(metrics, fontweight='bold')
    ax.legend(loc='upper left', framealpha=0.9)
    ax.set_ylim([0, 11])
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_dir / 'comparacion_arquitecturas.png', dpi=300, bbox_inches='tight')
    print(f"✓ Generado: comparacion_arquitecturas.png")
    plt.close()

# ============================================================================
# GRÁFICO 5: Costo Computacional del Feedback Loop
# ============================================================================
def plot_computational_cost():
    """Gráfico comparativo de costo vs beneficio"""
    categories = ['Llamadas\nal LLM', 'Tasa de\nAprobación']
    
    sin_feedback = [1008, 80.7]
    con_feedback = [1203, 100]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Subplot 1: Llamadas al LLM
    x = [0, 1]
    bars1 = ax1.bar(x, [sin_feedback[0], con_feedback[0]], 
                    color=['#3498db', '#e74c3c'], alpha=0.8,
                    edgecolor='black', linewidth=1.5, width=0.6)
    
    ax1.set_xticks(x)
    ax1.set_xticklabels(['Sin Feedback', 'Con Feedback'], fontweight='bold')
    ax1.set_ylabel('Número de Llamadas', fontweight='bold')
    ax1.set_title('Costo: Llamadas al LLM', fontweight='bold', pad=15)
    
    # Añadir valores y porcentaje de incremento
    for i, bar in enumerate(bars1):
        height = bar.get_height()
        label = f'{int(height):,}'
        if i == 1:
            incremento = ((con_feedback[0] - sin_feedback[0]) / sin_feedback[0] * 100)
            label += f'\n(+{incremento:.1f}%)'
        ax1.text(bar.get_x() + bar.get_width()/2., height + 20,
                label, ha='center', va='bottom', fontweight='bold', fontsize=11)
    
    ax1.grid(True, alpha=0.3, axis='y')
    
    # Subplot 2: Tasa de aprobación
    bars2 = ax2.bar(x, [sin_feedback[1], con_feedback[1]], 
                    color=['#3498db', '#2ecc71'], alpha=0.8,
                    edgecolor='black', linewidth=1.5, width=0.6)
    
    ax2.set_xticks(x)
    ax2.set_xticklabels(['Sin Feedback', 'Con Feedback'], fontweight='bold')
    ax2.set_ylabel('Tasa de Aprobación (%)', fontweight='bold')
    ax2.set_title('Beneficio: Tasa de Aprobación', fontweight='bold', pad=15)
    ax2.set_ylim([0, 110])
    
    # Añadir valores
    for i, bar in enumerate(bars2):
        height = bar.get_height()
        label = f'{height:.1f}%'
        if i == 1:
            mejora = con_feedback[1] - sin_feedback[1]
            label += f'\n(+{mejora:.1f}%)'
        ax2.text(bar.get_x() + bar.get_width()/2., height + 2,
                label, ha='center', va='bottom', fontweight='bold', fontsize=11)
    
    ax2.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_dir / 'costo_computacional.png', dpi=300, bbox_inches='tight')
    print(f"✓ Generado: costo_computacional.png")
    plt.close()

# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Generando gráficos para el informe de Tarea 2")
    print("=" * 60)
    
    plot_score_distribution()
    plot_feedback_effectiveness()
    plot_retry_funnel()
    plot_architecture_comparison()
    plot_computational_cost()
    
    print("=" * 60)
    print(f"✓ Todos los gráficos generados en: {output_dir}")
    print("=" * 60)

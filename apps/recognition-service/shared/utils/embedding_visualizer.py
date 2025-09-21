"""
Embedding Visualization Utilities

This module provides tools for visualizing face embeddings and their evolution
as new reference images are added to roster entries. Useful for understanding:
- How embeddings cluster for the same person
- How aggregate embeddings evolve with new images
- Relationships between different entities
- Quality of embedding consistency
"""

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
from datetime import datetime
import logging
from pathlib import Path

# Optional imports for enhanced visualizations
try:
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    logging.warning("Plotly not available. Using matplotlib for visualizations.")

from recognition.utils.face_utils import normalize_vec, cosine_similarity


class EmbeddingVisualizer:
    """
    Visualizes face embeddings and their evolution over time.
    """
    
    def __init__(self, save_dir: str = "data/visualizations"):
        """
        Initialize the visualizer.
        
        Args:
            save_dir: Directory to save visualization outputs
        """
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        
        # Track embedding history for animation
        self.embedding_history: List[Dict[str, Any]] = []
        
        # Set up plotting style
        plt.style.use('seaborn-v0_8' if 'seaborn-v0_8' in plt.style.available else 'default')
        sns.set_palette("husl")
    
    def add_embedding_snapshot(self, roster_entries: List[Dict[str, Any]], 
                             timestamp: Optional[str] = None) -> None:
        """
        Add a snapshot of current embeddings for temporal analysis.
        
        Args:
            roster_entries: List of roster entries with embeddings
            timestamp: Optional timestamp (defaults to current time)
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()
        
        snapshot = {
            'timestamp': timestamp,
            'entries': []
        }
        
        for entry in roster_entries:
            if 'aggregate_embedding' in entry and entry['aggregate_embedding'] is not None:
                snapshot['entries'].append({
                    'name': entry.get('name', 'unknown'),
                    'unique_id': entry.get('unique_id', 'unknown'),
                    'embedding': np.array(entry['aggregate_embedding']),
                    'image_count': entry.get('image_count', 0)
                })
        
        self.embedding_history.append(snapshot)
        logging.info(f"Added embedding snapshot with {len(snapshot['entries'])} entities")
    
    def visualize_embedding_space(self, roster_entries: List[Dict[str, Any]], 
                                method: str = 'pca', save_path: Optional[str] = None) -> None:
        """
        Visualize embeddings in 2D space using dimensionality reduction.
        
        Args:
            roster_entries: List of roster entries with embeddings
            method: Dimensionality reduction method ('pca', 'tsne')
            save_path: Optional path to save the plot
        """
        # Extract embeddings and labels
        embeddings = []
        labels = []
        image_counts = []
        
        for entry in roster_entries:
            if 'aggregate_embedding' in entry and entry['aggregate_embedding'] is not None:
                emb = np.array(entry['aggregate_embedding'])
                if len(emb) > 0:
                    embeddings.append(normalize_vec(emb))
                    labels.append(entry.get('name', 'unknown'))
                    image_counts.append(entry.get('image_count', 1))
        
        if len(embeddings) < 2:
            logging.warning("Need at least 2 embeddings for visualization")
            return
        
        embeddings = np.array(embeddings)
        
        # Apply dimensionality reduction
        if method.lower() == 'pca':
            reducer = PCA(n_components=2, random_state=42)
            reduced = reducer.fit_transform(embeddings)
            title = f"PCA of Face Embeddings (Explained Variance: {reducer.explained_variance_ratio_.sum():.2%})"
        elif method.lower() == 'tsne':
            reducer = TSNE(n_components=2, random_state=42, perplexity=min(30, len(embeddings)-1))
            reduced = reducer.fit_transform(embeddings)
            title = "t-SNE of Face Embeddings"
        else:
            raise ValueError(f"Unknown method: {method}")
        
        # Create the plot
        plt.figure(figsize=(12, 8))
        
        # Color by entity, size by number of images
        unique_labels = list(set(labels))
        colors = plt.cm.Set3(np.linspace(0, 1, len(unique_labels)))
        
        for i, label in enumerate(unique_labels):
            mask = np.array(labels) == label
            plt.scatter(reduced[mask, 0], reduced[mask, 1], 
                       c=[colors[i]], label=label, 
                       s=np.array(image_counts)[mask] * 50 + 100,  # Size by image count
                       alpha=0.7, edgecolors='black', linewidth=1)
        
        plt.title(title)
        plt.xlabel('Component 1')
        plt.ylabel('Component 2')
        plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.grid(True, alpha=0.3)
        
        # Add annotations
        for i, (x, y) in enumerate(reduced):
            plt.annotate(f'{labels[i]}\\n({image_counts[i]} imgs)', 
                        (x, y), xytext=(5, 5), textcoords='offset points',
                        fontsize=8, alpha=0.8)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logging.info(f"Saved embedding visualization to {save_path}")
        
        plt.show()
    
    def visualize_embedding_evolution(self, entity_name: str, 
                                    save_path: Optional[str] = None) -> None:
        """
        Visualize how an entity's embedding evolves as new images are added.
        
        Args:
            entity_name: Name of the entity to track
            save_path: Optional path to save the plot
        """
        if len(self.embedding_history) < 2:
            logging.warning("Need at least 2 snapshots for evolution visualization")
            return
        
        # Extract evolution data for the specific entity
        evolution_data = []
        for snapshot in self.embedding_history:
            for entry in snapshot['entries']:
                if entry['name'] == entity_name:
                    evolution_data.append({
                        'timestamp': snapshot['timestamp'],
                        'embedding': entry['embedding'],
                        'image_count': entry['image_count']
                    })
                    break
        
        if len(evolution_data) < 2:
            logging.warning(f"Insufficient data for entity {entity_name}")
            return
        
        # Calculate evolution metrics
        timestamps = [d['timestamp'] for d in evolution_data]
        image_counts = [d['image_count'] for d in evolution_data]
        
        # Calculate embedding stability (cosine similarity with first embedding)
        first_embedding = evolution_data[0]['embedding']
        similarities = []
        magnitudes = []
        
        for data in evolution_data:
            emb = data['embedding']
            sim = cosine_similarity(first_embedding, emb, normalize=True)
            similarities.append(float(sim))
            magnitudes.append(float(np.linalg.norm(emb)))
        
        # Create subplots
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
        
        # Plot 1: Embedding stability over time
        ax1.plot(range(len(similarities)), similarities, 'o-', linewidth=2)
        ax1.set_title(f'Embedding Stability for {entity_name}')
        ax1.set_xlabel('Image Addition Step')
        ax1.set_ylabel('Cosine Similarity to Initial')
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(0, 1)
        
        # Plot 2: Embedding magnitude evolution
        ax2.plot(range(len(magnitudes)), magnitudes, 'o-', color='orange', linewidth=2)
        ax2.set_title(f'Embedding Magnitude Evolution')
        ax2.set_xlabel('Image Addition Step')
        ax2.set_ylabel('L2 Norm')
        ax2.grid(True, alpha=0.3)
        
        # Plot 3: Image count over time
        ax3.plot(range(len(image_counts)), image_counts, 'o-', color='green', linewidth=2)
        ax3.set_title(f'Reference Image Count')
        ax3.set_xlabel('Image Addition Step')
        ax3.set_ylabel('Number of Images')
        ax3.grid(True, alpha=0.3)
        
        # Plot 4: Embedding dimension variance
        embedding_matrix = np.array([d['embedding'] for d in evolution_data])
        dimension_vars = np.var(embedding_matrix, axis=0)
        ax4.hist(dimension_vars, bins=50, alpha=0.7, color='purple')
        ax4.set_title(f'Embedding Dimension Variance Distribution')
        ax4.set_xlabel('Variance')
        ax4.set_ylabel('Number of Dimensions')
        ax4.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logging.info(f"Saved evolution visualization to {save_path}")
        
        plt.show()
    
    def plot_embedding_evolution(self, save_path: Optional[str] = None) -> None:
        """
        Plot embedding evolution for all entities across time snapshots.
        
        Args:
            save_path: Optional path to save the plot
        """
        if len(self.embedding_history) < 2:
            logging.warning("Need at least 2 snapshots for evolution visualization")
            return
            
        # Get all unique entity names
        all_entities = set()
        for snapshot in self.embedding_history:
            for entry in snapshot['entries']:
                all_entities.add(entry['name'])
        
        if not all_entities:
            logging.warning("No entities found in embedding history")
            return
            
        # Create plot
        plt.figure(figsize=(12, 8))
        
        # Track similarity evolution for each entity
        for entity_name in all_entities:
            similarities = []
            timestamps = []
            
            first_embedding = None
            for snapshot in self.embedding_history:
                for entry in snapshot['entries']:
                    if entry['name'] == entity_name:
                        if first_embedding is None:
                            first_embedding = entry['embedding']
                            similarities.append(1.0)  # Perfect similarity to self
                        else:
                            sim = cosine_similarity(first_embedding, entry['embedding'], normalize=True)
                            similarities.append(float(sim))
                        timestamps.append(snapshot['timestamp'])
                        break
            
            if len(similarities) > 1:
                plt.plot(range(len(similarities)), similarities, 'o-', 
                        label=entity_name, linewidth=2, markersize=6)
        
        plt.title('Embedding Stability Evolution Across All Entities')
        plt.xlabel('Time Step')
        plt.ylabel('Cosine Similarity to Initial Embedding')
        plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.grid(True, alpha=0.3)
        plt.ylim(0, 1)
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logging.info(f"Saved embedding evolution plot to {save_path}")
        
        plt.show()
    
    def create_similarity_heatmap(self, roster_entries: List[Dict[str, Any]], 
                                save_path: Optional[str] = None) -> None:
        """
        Create a heatmap showing cosine similarities between all entities.
        
        Args:
            roster_entries: List of roster entries with embeddings
            save_path: Optional path to save the plot
        """
        # Extract embeddings and names
        embeddings = []
        names = []
        
        for entry in roster_entries:
            if 'aggregate_embedding' in entry and entry['aggregate_embedding'] is not None:
                emb = np.array(entry['aggregate_embedding'])
                if len(emb) > 0:
                    embeddings.append(normalize_vec(emb))
                    names.append(entry.get('name', 'unknown'))
        
        if len(embeddings) < 2:
            logging.warning("Need at least 2 embeddings for similarity heatmap")
            return
        
        # Calculate similarity matrix
        n = len(embeddings)
        similarity_matrix = np.zeros((n, n))
        
        for i in range(n):
            for j in range(n):
                similarity_matrix[i, j] = cosine_similarity(embeddings[i], embeddings[j], normalize=False)
        
        # Create heatmap
        plt.figure(figsize=(10, 8))
        sns.heatmap(similarity_matrix, 
                   xticklabels=names, 
                   yticklabels=names,
                   annot=True, 
                   fmt='.3f',
                   cmap='RdYlBu_r',
                   center=0.5,
                   square=True,
                   cbar_kws={'label': 'Cosine Similarity'})
        
        plt.title('Entity Embedding Similarity Matrix')
        plt.xlabel('Entity')
        plt.ylabel('Entity')
        plt.xticks(rotation=45, ha='right')
        plt.yticks(rotation=0)
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logging.info(f"Saved similarity heatmap to {save_path}")
        
        plt.show()
    
    def create_interactive_3d_plot(self, roster_entries: List[Dict[str, Any]], 
                                 save_path: Optional[str] = None) -> None:
        """
        Create an interactive 3D plot of embeddings (requires plotly).
        
        Args:
            roster_entries: List of roster entries with embeddings
            save_path: Optional path to save the HTML plot
        """
        if not PLOTLY_AVAILABLE:
            logging.warning("Plotly not available. Install with: pip install plotly")
            return
        
        # Extract embeddings and metadata
        embeddings = []
        names = []
        image_counts = []
        
        for entry in roster_entries:
            if 'aggregate_embedding' in entry and entry['aggregate_embedding'] is not None:
                emb = np.array(entry['aggregate_embedding'])
                if len(emb) > 0:
                    embeddings.append(normalize_vec(emb))
                    names.append(entry.get('name', 'unknown'))
                    image_counts.append(entry.get('image_count', 1))
        
        if len(embeddings) < 3:
            logging.warning("Need at least 3 embeddings for 3D visualization")
            return
        
        embeddings = np.array(embeddings)
        
        # Apply PCA to 3D
        pca = PCA(n_components=3, random_state=42)
        reduced = pca.fit_transform(embeddings)
        
        # Create interactive 3D scatter plot
        fig = go.Figure(data=[go.Scatter3d(
            x=reduced[:, 0],
            y=reduced[:, 1],
            z=reduced[:, 2],
            mode='markers+text',
            marker=dict(
                size=[count * 5 + 10 for count in image_counts],
                color=range(len(names)),
                colorscale='Viridis',
                opacity=0.8,
                colorbar=dict(title="Entity Index")
            ),
            text=names,
            textposition="top center",
            hovertemplate='<b>%{text}</b><br>' +
                         'PC1: %{x:.3f}<br>' +
                         'PC2: %{y:.3f}<br>' +
                         'PC3: %{z:.3f}<br>' +
                         'Images: %{marker.size}<br>' +
                         '<extra></extra>'
        )])
        
        fig.update_layout(
            title=f'3D PCA of Face Embeddings (Explained Variance: {pca.explained_variance_ratio_.sum():.2%})',
            scene=dict(
                xaxis_title='PC1',
                yaxis_title='PC2',
                zaxis_title='PC3'
            ),
            width=900,
            height=700,
            margin=dict(r=20, b=10, l=10, t=40)
        )
        
        if save_path:
            fig.write_html(save_path)
            logging.info(f"Saved interactive 3D plot to {save_path}")
        
        fig.show()
    
    def generate_embedding_report(self, roster_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate a comprehensive report on embedding quality and statistics.
        
        Args:
            roster_entries: List of roster entries with embeddings
            
        Returns:
            Dictionary containing embedding statistics and quality metrics
        """
        report = {
            'timestamp': datetime.now().isoformat(),
            'total_entities': 0,
            'total_images': 0,
            'embedding_stats': {},
            'quality_metrics': {},
            'entities': []
        }
        
        embeddings = []
        
        for entry in roster_entries:
            if 'aggregate_embedding' in entry and entry['aggregate_embedding'] is not None:
                emb = np.array(entry['aggregate_embedding'])
                if len(emb) > 0:
                    embeddings.append(emb)
                    report['total_entities'] += 1
                    report['total_images'] += entry.get('image_count', 0)
                    
                    # Per-entity metrics
                    entity_stats = {
                        'name': entry.get('name', 'unknown'),
                        'image_count': entry.get('image_count', 0),
                        'embedding_norm': float(np.linalg.norm(emb)),
                        'embedding_mean': float(np.mean(emb)),
                        'embedding_std': float(np.std(emb)),
                        'embedding_dimension': len(emb)
                    }
                    report['entities'].append(entity_stats)
        
        if embeddings:
            embeddings = np.array(embeddings)
            
            # Overall embedding statistics
            report['embedding_stats'] = {
                'dimension': embeddings.shape[1],
                'mean_norm': float(np.mean([np.linalg.norm(emb) for emb in embeddings])),
                'std_norm': float(np.std([np.linalg.norm(emb) for emb in embeddings])),
                'mean_similarity': float(np.mean([
                    cosine_similarity(embeddings[i], embeddings[j], normalize=True)
                    for i in range(len(embeddings))
                    for j in range(i+1, len(embeddings))
                ])) if len(embeddings) > 1 else 0.0
            }
            
            # Quality metrics
            norms = [np.linalg.norm(emb) for emb in embeddings]
            report['quality_metrics'] = {
                'norm_consistency': float(1.0 - np.std(norms) / (np.mean(norms) + 1e-8)),
                'average_inter_entity_similarity': report['embedding_stats']['mean_similarity'],
                'embedding_separability': float(1.0 - report['embedding_stats']['mean_similarity'])
            }
        
        return report


def integrate_with_roster_client():
    """
    Integration function to add visualization capabilities to the roster client.
    This can be called from the mock_roster_client.py to enable real-time visualization.
    """
    
    def visualize_roster_embeddings(roster_entries: List[Dict[str, Any]], 
                                   output_dir: str = "data/visualizations"):
        """
        Visualize roster embeddings with multiple plot types.
        
        Args:
            roster_entries: List of roster entries from API
            output_dir: Directory to save visualizations
        """
        visualizer = EmbeddingVisualizer(save_dir=output_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Add current snapshot
        visualizer.add_embedding_snapshot(roster_entries)
        
        # Generate all visualizations
        try:
            # 2D PCA visualization
            visualizer.visualize_embedding_space(
                roster_entries, method='pca', 
                save_path=f"{output_dir}/pca_{timestamp}.png"
            )
            
            # t-SNE visualization
            visualizer.visualize_embedding_space(
                roster_entries, method='tsne',
                save_path=f"{output_dir}/tsne_{timestamp}.png"
            )
            
            # Similarity heatmap
            visualizer.create_similarity_heatmap(
                roster_entries,
                save_path=f"{output_dir}/similarity_{timestamp}.png"
            )
            
            # Interactive 3D plot (if plotly available)
            visualizer.create_interactive_3d_plot(
                roster_entries,
                save_path=f"{output_dir}/interactive_3d_{timestamp}.html"
            )
            
            # Generate report
            report = visualizer.generate_embedding_report(roster_entries)
            with open(f"{output_dir}/embedding_report_{timestamp}.json", 'w') as f:
                import json
                json.dump(report, f, indent=2)
            
            logging.info(f"Generated embedding visualizations in {output_dir}")
            
        except Exception as e:
            logging.error(f"Error generating visualizations: {e}")
    
    return visualize_roster_embeddings


# Example usage
if __name__ == "__main__":
    # Example of how this would be used
    print("Embedding visualization utilities loaded.")
    print("To use with roster client, import and call integrate_with_roster_client()")
    print("Example usage:")
    print("  from utils.embedding_visualizer import integrate_with_roster_client")
    print("  visualize_func = integrate_with_roster_client()")
    print("  visualize_func(roster_entries)")

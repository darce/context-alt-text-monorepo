"""
Embedding Router Implementation
Concrete implementation of embedding routing for roster data management.
"""
import logging
import json
import os
from typing import Dict, Optional
from pathlib import Path
import numpy as np
from threading import RLock

from ..domain import EmbeddingRouter, ModelType

logger = logging.getLogger(__name__)


class EmbeddingRouterImpl(EmbeddingRouter):
    """
    Embedding router implementation for managing roster embeddings.
    
    Maps model types to their corresponding embedding files and handles
    automatic reloading based on file modification times.
    """
    
    def __init__(self, roster_dir: str = "datasets/micro/roster"):
        """
        Initialize embedding router.
        
        Args:
            roster_dir: Directory containing roster embedding files
        """
        self.roster_dir = Path(roster_dir)
        self.embedding_cache: Dict[ModelType, Dict[str, np.ndarray]] = {}
        self.file_mtimes: Dict[ModelType, float] = {}
        self.lock = RLock()
        
        # Model type to filename mapping - updated for complete augmented embeddings
        # Prioritize complete rosters with all entities for each model
        self.model_files = {
            ModelType.ADAFACE_IR101: [
                "adaface_ir101_complete_roster.json",    # Complete roster (preferred)
                "adaface_ir101_micro_10_roster.json",    # Micro dataset (fallback)
                "adaface_ir101_benchmark_roster.json",   # Legacy benchmark format
                "adaface_ir101_embeddings.json"          # Simple format (fallback)
            ],
            ModelType.INSIGHTFACE_W600K: [
                "insightface_w600k_complete_roster.json", # Complete roster (preferred)
                "insightface_w600k_micro_10_roster.json", # Micro dataset (fallback)
                "insightface_w600k_benchmark_roster.json", # Legacy benchmark format
                "insightface_w600k_embeddings.json"       # Simple format (fallback)
            ],
            ModelType.ARCFACE_IR101: [
                "arcface_ir101_complete_roster.json",    # Complete roster (preferred)
                "arcface_ir50_micro_10_roster.json",     # Micro dataset (fallback)
                "arcface_ir50_benchmark_roster.json",    # Legacy benchmark format
                "arcface_ir50_embeddings.json"           # Simple format (fallback)
            ]
        }
        
        logger.info(f"✅ Embedding router initialized with roster dir: {self.roster_dir}")
        
        # Pre-load embeddings
        self._preload_embeddings()
    
    def get_embeddings(self, model_type: ModelType) -> Dict[str, np.ndarray]:
        """
        Get embeddings for a specific model type.
        
        Args:
            model_type: Type of model requesting embeddings
            
        Returns:
            Dictionary mapping person names to embeddings
        """
        with self.lock:
            # Check if embeddings need to be reloaded
            if self._should_reload_embeddings(model_type):
                self._load_embeddings(model_type)
            
            return self.embedding_cache.get(model_type, {})
    
    def reload_embeddings(self, model_type: ModelType) -> bool:
        """
        Reload embeddings from storage for a model type.
        
        Args:
            model_type: Type of model to reload embeddings for
            
        Returns:
            True if reload successful, False otherwise
        """
        with self.lock:
            try:
                self._load_embeddings(model_type)
                logger.info(f"✅ Embeddings reloaded for {model_type}")
                return True
            except Exception as e:
                logger.error(f"❌ Failed to reload embeddings for {model_type}: {e}")
                return False
    
    def _preload_embeddings(self):
        """Preload embeddings for all model types."""
        for model_type in ModelType:
            try:
                self._load_embeddings(model_type)
                logger.info(f"✅ Preloaded embeddings for {model_type}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to preload embeddings for {model_type}: {e}")
    
    def _should_reload_embeddings(self, model_type: ModelType) -> bool:
        """
        Check if embeddings should be reloaded based on file modification time.
        
        Args:
            model_type: Model type to check
            
        Returns:
            True if embeddings should be reloaded
        """
        try:
            file_path = self._get_embedding_file_path(model_type)
            
            if not file_path.exists():
                return model_type not in self.embedding_cache
            
            current_mtime = file_path.stat().st_mtime
            cached_mtime = self.file_mtimes.get(model_type, 0)
            
            return current_mtime > cached_mtime
            
        except Exception as e:
            logger.error(f"Error checking file modification time: {e}")
            return False
    
    def _load_embeddings(self, model_type: ModelType):
        """
        Load embeddings from file for a model type.
        Supports both roster format and simple embedding format.
        
        Args:
            model_type: Model type to load embeddings for
        """
        file_path = self._get_embedding_file_path(model_type)
        
        if not file_path.exists():
            logger.warning(f"Embedding file not found: {file_path}")
            self.embedding_cache[model_type] = {}
            return
        
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            embeddings = {}
            
            # Check if this is roster format
            if 'entries' in data and isinstance(data['entries'], list):
                # Roster format - extract from entries
                logger.info(f"Loading roster format from {file_path}")
                for entry in data['entries']:
                    person_name = entry.get('name')
                    embedding_data = None
                    
                    # Support both 'aggregate_embedding' (legacy) and 'embedding' (new)
                    if 'aggregate_embedding' in entry:
                        embedding_data = entry['aggregate_embedding']
                    elif 'embedding' in entry:
                        embedding_data = entry['embedding']
                    
                    if person_name and embedding_data:
                        embeddings[person_name] = np.array(embedding_data, dtype=np.float32)
                        logger.debug(f"Loaded {person_name}: {len(embedding_data)} dimensions")
                    else:
                        logger.warning(f"Invalid roster entry format: {list(entry.keys())}")
            else:
                # Simple embedding format - legacy support
                logger.info(f"Loading simple embedding format from {file_path}")
                for person_name, embedding_data in data.items():
                    if isinstance(embedding_data, list):
                        # Simple list format
                        embeddings[person_name] = np.array(embedding_data, dtype=np.float32)
                    elif isinstance(embedding_data, dict):
                        # Dictionary format with metadata
                        if 'embedding' in embedding_data:
                            embeddings[person_name] = np.array(embedding_data['embedding'], dtype=np.float32)
                        else:
                            logger.warning(f"Invalid embedding format for {person_name}")
                            continue
                    else:
                        logger.warning(f"Unknown embedding format for {person_name}")
                        continue
            
            self.embedding_cache[model_type] = embeddings
            self.file_mtimes[model_type] = file_path.stat().st_mtime
            
            logger.info(f"✅ Loaded {len(embeddings)} embeddings for {model_type} from {file_path.name}")
            
        except Exception as e:
            logger.error(f"❌ Failed to load embeddings from {file_path}: {e}")
            self.embedding_cache[model_type] = {}
    
    def _get_embedding_file_path(self, model_type: ModelType) -> Path:
        """
        Get the file path for a model type's embeddings.
        Checks for roster format first, then falls back to simple format.
        
        Args:
            model_type: Model type
            
        Returns:
            Path to embedding file
        """
        filenames = self.model_files.get(model_type)
        if not filenames:
            raise ValueError(f"No embedding file configured for {model_type}")
        
        # Check each filename in order of preference
        for filename in filenames:
            file_path = self.roster_dir / filename
            if file_path.exists():
                return file_path
        
        # If no files exist, return the first one (for error reporting)
        return self.roster_dir / filenames[0]
    
    def get_embedding_stats(self) -> Dict[str, Dict[str, any]]:
        """
        Get statistics about loaded embeddings.
        
        Returns:
            Dictionary with embedding statistics
        """
        stats = {}
        
        with self.lock:
            for model_type, embeddings in self.embedding_cache.items():
                if embeddings:
                    embedding_dims = [emb.shape[0] for emb in embeddings.values()]
                    stats[model_type.value] = {
                        'count': len(embeddings),
                        'persons': list(embeddings.keys()),
                        'embedding_dim': embedding_dims[0] if embedding_dims else 0,
                        'file_path': str(self._get_embedding_file_path(model_type)),
                        'last_modified': self.file_mtimes.get(model_type, 0)
                    }
                else:
                    stats[model_type.value] = {
                        'count': 0,
                        'persons': [],
                        'embedding_dim': 0,
                        'file_path': str(self._get_embedding_file_path(model_type)),
                        'last_modified': 0
                    }
        
        return stats
    
    def add_embedding(self, model_type: ModelType, person_name: str, 
                     embedding: np.ndarray, save_to_file: bool = True) -> bool:
        """
        Add a new embedding to the roster.
        
        Args:
            model_type: Model type for the embedding
            person_name: Name of the person
            embedding: Face embedding
            save_to_file: Whether to save to file immediately
            
        Returns:
            True if successful, False otherwise
        """
        with self.lock:
            try:
                # Add to cache
                if model_type not in self.embedding_cache:
                    self.embedding_cache[model_type] = {}
                
                self.embedding_cache[model_type][person_name] = embedding
                
                # Save to file if requested
                if save_to_file:
                    self._save_embeddings_to_file(model_type)
                
                logger.info(f"✅ Added embedding for {person_name} ({model_type})")
                return True
                
            except Exception as e:
                logger.error(f"❌ Failed to add embedding for {person_name}: {e}")
                return False
    
    def _save_embeddings_to_file(self, model_type: ModelType):
        """
        Save embeddings to file.
        
        Args:
            model_type: Model type to save
        """
        file_path = self._get_embedding_file_path(model_type)
        
        # Create directory if it doesn't exist
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert embeddings to serializable format
        embeddings = self.embedding_cache.get(model_type, {})
        serializable_data = {}
        
        for person_name, embedding in embeddings.items():
            serializable_data[person_name] = {
                'embedding': embedding.tolist(),
                'model_type': model_type.value,
                'embedding_dim': embedding.shape[0]
            }
        
        # Save to file
        with open(file_path, 'w') as f:
            json.dump(serializable_data, f, indent=2)
        
        # Update modification time
        self.file_mtimes[model_type] = file_path.stat().st_mtime
        
        logger.info(f"✅ Saved {len(embeddings)} embeddings to {file_path}")

"""
Embedding Storage Adapter

Handles model-specific embedding files and hot-reload functionality.
Manages the embedding JSON files used by the recognition service.
"""

import json
import os
import logging
import threading
import time
from typing import List, Dict, Any, Callable, Optional
from pathlib import Path
from datetime import datetime

# Optional dependency for file watching
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    Observer = None
    FileSystemEventHandler = None
    WATCHDOG_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("watchdog not available, file watching disabled")

from ..domain.interfaces import EmbeddingStoragePort
from ..domain.entities import RosterEntry
from ..config import get_config

logger = logging.getLogger(__name__)


class EmbeddingFileHandler:
    """File watcher handler for embedding files."""
    
    def __init__(self, callback: Callable[[str], None], model: str):
        """
        Initialize file handler.
        
        Args:
            callback: Function to call when file changes
            model: Model identifier
        """
        if not WATCHDOG_AVAILABLE:
            raise ImportError("watchdog package required for file watching")
        
        # Only inherit from FileSystemEventHandler if watchdog is available
        if FileSystemEventHandler:
            self.__class__.__bases__ = (FileSystemEventHandler,)
        
        self.callback = callback
        self.model = model
        self.last_modified = 0
        
    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return
            
        # Debounce rapid successive events
        current_time = time.time()
        if current_time - self.last_modified < 0.5:
            return
        self.last_modified = current_time
        
        try:
            self.callback(self.model)
        except Exception as e:
            logger.error(f"Error in file watcher callback: {e}")


class EmbeddingStorageAdapter(EmbeddingStoragePort):
    """
    Filesystem-based embedding storage adapter.
    
    Manages embedding JSON files and provides hot-reload functionality
    compatible with the recognition service.
    """
    
    def __init__(self):
        """Initialize embedding storage adapter."""
        self.config = get_config()
        self.data_dir = self.config.get_data_dir()
        self._ensure_data_dir()
        self._watchers: Dict[str, Any] = {}  # Use Any instead of Observer type
        self._locks = {}  # Per-model file locks
        
    def _ensure_data_dir(self):
        """Ensure data directory exists."""
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        logger.info(f"Embedding data directory: {self.data_dir}")
    
    def _get_lock(self, model: str) -> threading.Lock:
        """Get or create a lock for the model."""
        if model not in self._locks:
            self._locks[model] = threading.Lock()
        return self._locks[model]
    
    def _get_embeddings_file_path(self, model: str) -> str:
        """Get the embeddings file path for a model."""
        return self.config.get_embeddings_file_path(model)
    
    def save_embeddings(self, entries: List[RosterEntry], model: str) -> bool:
        """
        Save embeddings to model-specific storage.
        
        Creates embedding file compatible with recognition service format.
        """
        with self._get_lock(model):
            try:
                embeddings_file = self._get_embeddings_file_path(model)
                temp_file = f"{embeddings_file}.tmp"
                
                # Convert roster entries to embedding format
                embedding_data = []
                for entry in entries:
                    if not entry.aggregate_embedding:
                        continue
                        
                    embedding_entry = {
                        "name": entry.name,
                        "unique_id": entry.unique_id,
                        "display_name": entry.display_name,
                        "embedding": entry.aggregate_embedding,
                        "metadata": entry.metadata,
                        "created_timestamp": entry.created_timestamp,
                        "updated_timestamp": entry.updated_timestamp,
                        "image_count": entry.image_count
                    }
                    embedding_data.append(embedding_entry)
                
                # Create data structure
                data = {
                    "metadata": {
                        "model": model,
                        "version": "1.0.0",
                        "format": "cvlface_embeddings",
                        "updated": datetime.now().isoformat(),
                        "entry_count": len(embedding_data)
                    },
                    "embeddings": embedding_data
                }
                
                # Write to temporary file first
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                # Atomic move to final location
                os.replace(temp_file, embeddings_file)
                logger.info(f"Saved embeddings file: {embeddings_file} ({len(embedding_data)} entries)")
                return True
                
            except Exception as e:
                logger.error(f"Error saving embeddings for {model}: {e}")
                # Clean up temp file if it exists
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
                return False
    
    def load_embeddings(self, model: str) -> List[Dict[str, Any]]:
        """
        Load embeddings from model-specific storage.
        
        Returns embedding data compatible with recognition service.
        """
        with self._get_lock(model):
            try:
                embeddings_file = self._get_embeddings_file_path(model)
                
                if not os.path.exists(embeddings_file):
                    logger.debug(f"Embeddings file not found: {embeddings_file}")
                    return []
                
                with open(embeddings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Handle both old and new formats
                if isinstance(data, list):
                    # Legacy format
                    return data
                elif isinstance(data, dict) and 'embeddings' in data:
                    # New format
                    return data['embeddings']
                else:
                    logger.warning(f"Unexpected embeddings file format: {embeddings_file}")
                    return []
                    
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in embeddings file {embeddings_file}: {e}")
                return []
            except Exception as e:
                logger.error(f"Error loading embeddings for {model}: {e}")
                return []
    
    def watch_embeddings_file(self, model: str, callback: Callable[[str], None]) -> bool:
        """
        Set up file watcher for hot-reload functionality.
        
        Args:
            model: Model identifier
            callback: Function to call when file changes
            
        Returns:
            True if watcher set up successfully, False otherwise
        """
        try:
            if not self.config.is_hot_reload_enabled():
                logger.info("Hot-reload disabled in configuration")
                return False
            
            if not WATCHDOG_AVAILABLE:
                logger.warning("watchdog package not available, file watching disabled")
                return False
            
            embeddings_file = self._get_embeddings_file_path(model)
            watch_dir = os.path.dirname(embeddings_file)
            
            if not os.path.exists(watch_dir):
                Path(watch_dir).mkdir(parents=True, exist_ok=True)
            
            # Stop existing watcher for this model
            if model in self._watchers:
                self._watchers[model].stop()
                self._watchers[model].join()
            
            # Create new watcher
            event_handler = EmbeddingFileHandler(callback, model)
            observer = Observer()
            observer.schedule(event_handler, watch_dir, recursive=False)
            observer.start()
            
            self._watchers[model] = observer
            logger.info(f"Started file watcher for {model}: {watch_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting up file watcher for {model}: {e}")
            return False
    
    def stop_watching(self, model: str) -> bool:
        """
        Stop file watcher for a model.
        
        Args:
            model: Model identifier
            
        Returns:
            True if stopped successfully, False otherwise
        """
        try:
            if model in self._watchers:
                self._watchers[model].stop()
                self._watchers[model].join()
                del self._watchers[model]
                logger.info(f"Stopped file watcher for {model}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error stopping file watcher for {model}: {e}")
            return False
    
    def stop_all_watchers(self):
        """Stop all file watchers."""
        for model in list(self._watchers.keys()):
            self.stop_watching(model)
    
    def get_file_info(self, model: str) -> Dict[str, Any]:
        """
        Get information about the embeddings file.
        
        Args:
            model: Model identifier
            
        Returns:
            File information dictionary
        """
        embeddings_file = self._get_embeddings_file_path(model)
        
        info = {
            "model": model,
            "file_path": embeddings_file,
            "exists": os.path.exists(embeddings_file),
            "watching": model in self._watchers
        }
        
        if info["exists"]:
            try:
                stat = os.stat(embeddings_file)
                info.update({
                    "file_size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
                
                # Get entry count from file
                embeddings = self.load_embeddings(model)
                info["entry_count"] = len(embeddings)
                
            except Exception as e:
                logger.warning(f"Error getting file stats for {model}: {e}")
        
        return info

import importlib
import logging
import os
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional, Callable
from analysis.ports.object_detection_base import IObjectDetector
from analysis.ports.caption_generation_base import ICaptionGeneration
from roster.domain.interfaces import RosterStoragePort
from shared.infrastructure.gpu_manager import get_gpu_manager

# Module-level imports for all adapters
from analysis.adapters.yolo_adapter import YoloAdapter
from analysis.adapters.mock_yolo_adapter import MockYoloAdapter
from analysis.adapters.mock_caption_adapter import MockCaptionAdapter
from analysis.adapters.phi3_caption_adapter import Phi3CaptionAdapter
from roster.adapters.postgresql_storage_adapter import PostgreSQLStorageAdapter
from roster.adapters.sqlite_storage_adapter import SQLiteStorageAdapter


class AdapterFactory:
    """
    Factory for creating and configuring adapters.
    
    Uses a registry pattern to reduce code duplication and make adding
    new adapters simpler and less error-prone.
    """
    
    # Registry of object detector adapters
    _OBJECT_DETECTOR_REGISTRY: Dict[str, type] = {
        "yolo": YoloAdapter,
        "mock_yolo": MockYoloAdapter,
    }
    
    # Registry of caption generator adapters
    _CAPTION_GENERATOR_REGISTRY: Dict[str, type] = {
        "mock": MockCaptionAdapter,
        "phi3": Phi3CaptionAdapter,
    }
    
    # Registry of storage adapters
    _STORAGE_ADAPTER_REGISTRY: Dict[str, type] = {
        "postgresql": PostgreSQLStorageAdapter,
        "sqlite": SQLiteStorageAdapter,
    }
    
    @classmethod
    def register_object_detector(cls, name: str, adapter_class: type) -> None:
        """Register a new object detector adapter type."""
        cls._OBJECT_DETECTOR_REGISTRY[name] = adapter_class
        logging.info(f"Registered object detector adapter: {name}")
    
    @classmethod
    def register_caption_generator(cls, name: str, adapter_class: type) -> None:
        """Register a new caption generator adapter type."""
        cls._CAPTION_GENERATOR_REGISTRY[name] = adapter_class
        logging.info(f"Registered caption generator adapter: {name}")
    
    @classmethod
    def register_storage_adapter(cls, name: str, adapter_class: type) -> None:
        """Register a new storage adapter type."""
        cls._STORAGE_ADAPTER_REGISTRY[name] = adapter_class
        logging.info(f"Registered storage adapter: {name}")
    
    @staticmethod
    def create_adapters(config: Dict[str, Any]) -> Tuple[IObjectDetector, Optional[ICaptionGeneration]]:
        """
        Create and return instances of the required adapters
        :param config: Configuration dictionary containing adapter settings and global config.
        :return: A tuple of initialized adapter instances.
        """
        logging.info("Creating adapters based on configuration.")

        object_detector = AdapterFactory._create_object_detector(config.get("object_detector", {}))
        caption_generator = AdapterFactory._get_or_create_caption_generator(config.get("caption_generator", {}))

        AdapterFactory._initialize_adapter(object_detector, "object detector")
        if caption_generator is not None:
            AdapterFactory._initialize_adapter(caption_generator, "caption generator")

        return object_detector, caption_generator
    
    @staticmethod
    def _initialize_adapter(adapter, name: str):
        """Initialize an adapter if it supports initialization."""
        if hasattr(adapter, 'initialize') and hasattr(adapter, 'is_ready'):
            if not adapter.is_ready():
                logging.info(f"Initializing {name}...")
                try:
                    adapter.initialize()
                    if adapter.is_ready():
                        logging.info(f"✅ {name} initialized successfully")
                    else:
                        logging.error(f"❌ {name} initialization completed but adapter reports not ready")
                except Exception as e:
                    logging.error(f"❌ Failed to initialize {name}: {e}")
                    raise
            else:
                logging.info(f"{name} already initialized")
    
    @staticmethod
    def _create_object_detector(config: Dict[str, Any]) -> IObjectDetector:
        """Create object detector adapter from registry."""
        adapter_type = config.get("type")
        adapter_config = config.get("config", {})
        model_path = adapter_config.get("model_path")
        
        # Ensure model_path is provided from config
        if not model_path:
            raise ValueError("model_path must be specified in configuration")
        
        # Look up adapter class in registry
        adapter_class = AdapterFactory._OBJECT_DETECTOR_REGISTRY.get(adapter_type)
        if not adapter_class:
            raise ValueError(
                f"Unsupported object detection adapter type: {adapter_type}. "
                f"Available types: {list(AdapterFactory._OBJECT_DETECTOR_REGISTRY.keys())}"
            )
        
        # Resolve device specification
        resolved_device = AdapterFactory._resolve_device("Object detector", adapter_config)
        
        # Create adapter instance
        return adapter_class(
            model_path=model_path,
            device=resolved_device,
            confidence_threshold=adapter_config.get("confidence_threshold", 0.5),
            config=adapter_config
        )
    
    @staticmethod
    def _create_caption_generator(config: Dict[str, Any]) -> Optional[ICaptionGeneration]:
        """Create caption generator adapter from registry or custom class path."""
        adapter_type = config.get("type")
        adapter_config = config.get("config", {})

        if not adapter_type:
            logging.info("AdapterFactory: no caption generator configured; returning None")
            return None

        # Try registry first
        adapter_class = AdapterFactory._CAPTION_GENERATOR_REGISTRY.get(adapter_type)
        
        if adapter_class:
            # Handle registry-based adapters
            if adapter_type == "mock":
                logging.info("Using MockCaptionAdapter")
                return adapter_class()
            
            if adapter_type == "phi3":
                model_id = adapter_config.get("model_id")
                if not model_id:
                    raise ValueError("Caption generator config requires 'model_id' for phi3 adapter")
                resolved_device = AdapterFactory._resolve_device("Caption generator", adapter_config)
                return adapter_class(
                    model_id=model_id,
                    device=resolved_device,
                    config=adapter_config
                )

        # Fall back to custom class path for extensibility
        class_path = config.get("class_path") or adapter_config.get("class_path")
        if not class_path:
            raise ValueError(
                f"Unsupported caption generator type: {adapter_type}. "
                f"Available types: {list(AdapterFactory._CAPTION_GENERATOR_REGISTRY.keys())} "
                f"or provide 'class_path' for custom adapters."
            )

        module_name, class_name = class_path.rsplit('.', 1)
        logging.info("Loading custom caption adapter %s", class_path)
        module = importlib.import_module(module_name)
        adapter_cls = getattr(module, class_name)

        init_kwargs = adapter_config.get("init_kwargs", {})
        if "device" not in init_kwargs:
            try:
                resolved_device = AdapterFactory._resolve_device("Caption generator", adapter_config)
                init_kwargs.setdefault("device", resolved_device)
            except Exception:
                pass

        return adapter_cls(**init_kwargs)
    
    @staticmethod
    def create_roster_storage(config: Dict[str, Any]) -> RosterStoragePort:
        """
        Create and return a roster storage adapter from the registry.

        Production runs use PostgreSQL 17+ with the pgvector extension; unit
        tests may supply an in-memory SQLite URL for lightweight isolation.

        :param config: Configuration dictionary containing roster storage settings.
        :return: An initialized roster storage instance.
        """
        storage_config = config.get("config", {})

        database_url = storage_config.get("database_url") or os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError(
                "DATABASE_URL is required. "
                "This project requires PostgreSQL 17+ with pgvector extension for production. "
                "Example: postgresql://user:pass@localhost:5432/recognition"
            )

        # Normalise scheme (e.g., postgresql+psycopg -> postgresql)
        raw_scheme = database_url.split(":", 1)[0]
        scheme = raw_scheme.split("+", 1)[0]

        adapter_class = AdapterFactory._STORAGE_ADAPTER_REGISTRY.get(scheme)
        if adapter_class is None:
            raise ValueError(
                f"Unsupported DATABASE_URL scheme '{raw_scheme}'. "
                f"Available storage adapters: {list(AdapterFactory._STORAGE_ADAPTER_REGISTRY.keys())}"
            )

        tenant_id = storage_config.get("tenant_id") or os.getenv("DEFAULT_TENANT_ID")

        adapter_kwargs: Dict[str, Any] = {
            "database_url": database_url,
            "tenant_id": tenant_id,
        }

        if scheme == "postgresql":
            adapter_kwargs.update(
                pool_size=storage_config.get("pool_size", 5),
                max_overflow=storage_config.get("max_overflow", 10),
                pool_timeout=storage_config.get("pool_timeout", 30),
            )

        logging.info("Creating %s roster storage adapter (%s)", scheme, database_url)
        return adapter_class(**adapter_kwargs)
    
    def _resolve_device(name: str, adapter_config: Dict[str, Any]) -> str:
        """
        Helper to resolve and log device specification for adapters.
        """
        device_spec = adapter_config.get("device", "cpu")
        resolved = get_gpu_manager().resolve_device_spec(device_spec)
        logging.info(f"{name} device resolved: {device_spec} -> {resolved}")
        return resolved
    
    @staticmethod
    def _get_or_create_caption_generator(config: Dict[str, Any]) -> ICaptionGeneration:
        """Get preloaded caption adapter or create a new one if not available"""
        try:
            # Try to get the preloaded caption adapter from the global scope
            import app
            if hasattr(app, 'preloaded_caption_adapter') and app.preloaded_caption_adapter is not None:
                logging.info("Reusing preloaded caption adapter from lifespan")
                return app.preloaded_caption_adapter
        except (ImportError, AttributeError):
            logging.info("No preloaded caption adapter found, creating new one")
        
        # Fallback to creating a new caption generator
        return AdapterFactory._create_caption_generator(config)
    
    @staticmethod
    def create_entity_identifiers(config: Dict[str, Any], roster_service=None) -> List:
        """Simplified architecture does not use standalone entity identifier adapters."""
        logging.info("AdapterFactory: entity identifier adapters are disabled; returning empty list")
        return []

import importlib
import logging
from typing import Dict, Any, Tuple, List, Optional
from analysis.ports.object_detection_base import IObjectDetector
from analysis.ports.caption_generation_base import ICaptionGeneration
from roster.domain.interfaces import RosterStoragePort
from shared.infrastructure.gpu_manager import get_gpu_manager


class AdapterFactory:
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
        adapter_type = config.get("type")
        adapter_config = config.get("config", {})
        model_path = adapter_config.get("model_path")
        
        # Ensure model_path is provided from config
        if not model_path:
            raise ValueError("model_path must be specified in configuration")
        
        # Resolve device specification
        resolved_device = AdapterFactory._resolve_device("Object detector", adapter_config)
        
        if adapter_type == "yolo":
            from analysis.adapters.yolo_adapter import YoloAdapter
            return YoloAdapter(
                model_path=model_path,
                device=resolved_device,
                confidence_threshold=adapter_config["confidence_threshold"],
                config=adapter_config
            )
        elif adapter_type == "mock_yolo":
            from analysis.adapters.mock_yolo_adapter import MockYoloAdapter
            return MockYoloAdapter(
                device=resolved_device,
                confidence_threshold=adapter_config.get("confidence_threshold", 0.5),
                config=adapter_config
            )
        else:
            raise ValueError(f"Unsupported object detection adapter type: {adapter_type}")
    
    @staticmethod
    def _create_caption_generator(config: Dict[str, Any]) -> Optional[ICaptionGeneration]:
        adapter_type = config.get("type")
        adapter_config = config.get("config", {})

        if not adapter_type:
            logging.info("AdapterFactory: no caption generator configured; returning None")
            return None

        if adapter_type == "mock":
            from analysis.adapters.mock_caption_adapter import MockCaptionAdapter
            logging.info("Using MockCaptionAdapter")
            return MockCaptionAdapter()

        if adapter_type == "phi3":
            from analysis.adapters.phi3_caption_adapter import Phi3CaptionAdapter
            model_id = adapter_config.get("model_id")
            if not model_id:
                raise ValueError("Caption generator config requires 'model_id' for phi3 adapter")
            resolved_device = AdapterFactory._resolve_device("Caption generator", adapter_config)
            return Phi3CaptionAdapter(
                model_id=model_id,
                device=resolved_device,
                config=adapter_config
            )

        class_path = config.get("class_path") or adapter_config.get("class_path")
        if not class_path:
            raise ValueError(
                "Unsupported caption generator type. Provide 'class_path' for custom adapters."
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
        Create and return an instance of the roster storage adapter.
        
        :param config: Configuration dictionary containing roster storage settings.
        :return: An initialized roster storage instance.
        """
        storage_type = config.get("type", "file")
        storage_config = config.get("config", {})
        
        if storage_type == "file":
            from roster.adapters.file_storage_adapter import FileRosterStorageAdapter
            
            logging.info(f"Creating file roster storage adapter")
            
            return FileRosterStorageAdapter()
            
        elif storage_type == "database":
            # Future implementation for database storage
            raise NotImplementedError("Database roster storage not yet implemented")
            
        else:
            raise ValueError(f"Unsupported roster storage type: {storage_type}")
    
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

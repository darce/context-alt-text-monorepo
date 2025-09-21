import logging
from typing import Dict, Any, Tuple, List, Optional
from analysis.ports.object_detection_base import IObjectDetector
from recognition.domain.interfaces import RecognitionPort
from analysis.ports.caption_generation_base import ICaptionGeneration
from roster.domain.interfaces import RosterStoragePort
from recognition.ports.face_detection_base import IFaceDetection
from shared.infrastructure.gpu_manager import get_gpu_manager


class AdapterFactory:
    @staticmethod
    def create_adapters(config: Dict[str, Any]) -> Tuple[IObjectDetector, RecognitionPort, ICaptionGeneration]:
        """
        Create and return instances of the required adapters
        :param config: Configuration dictionary containing adapter settings and global config.
        :return: A tuple of initialized adapter instances.
        """
        logging.info("Creating adapters based on configuration.")
        
        # Obtain the singleton RosterService and its already-initialized entity_identifier via DI
        try:
            from api.dependencies import get_roster_service
            roster_service = get_roster_service()
            entity_identifier = roster_service.entity_identifier
            logging.info("AdapterFactory: Reusing entity_identifier from DI for adapter creation")
        except Exception:
            roster_service = None
            entity_identifier = None
            logging.warning("AdapterFactory: Could not obtain RosterService via DI, falling back")
         
        object_detector = AdapterFactory._create_object_detector(config.get("object_detector", {}))
        # If DI provided entity_identifier, use it; otherwise create a new one
        if entity_identifier is None:
            entity_identifier = AdapterFactory._create_entity_identifier(
                config.get("entity_identifier", {}),
                roster_service,
                config  # Pass the entire config for adapter configuration
            )
        
        # Check if we can reuse the preloaded caption adapter from lifespan
        caption_generator = AdapterFactory._get_or_create_caption_generator(config.get("caption_generator", {}))
        
        # Initialize adapters that support it (skip caption generator if already loaded)
        if not (hasattr(caption_generator, 'is_ready') and caption_generator.is_ready()):
            AdapterFactory._initialize_adapter(caption_generator, "caption generator")
        else:
            logging.info("Caption generator already initialized - reusing existing instance")
            
        AdapterFactory._initialize_adapter(object_detector, "object detector")
        AdapterFactory._initialize_adapter(entity_identifier, "entity identifier")
        
        return object_detector, entity_identifier, caption_generator
    
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
    def _create_entity_identifier(config: Dict[str, Any], roster_service=None, global_config: Dict[str, Any] = None) -> RecognitionPort:
        adapter_type = config.get("type")
        # Load adapter-specific config block (e.g., adaface_config, insightface_config), fallback to generic 'config'
        adapter_specific = config.get(f"{adapter_type.lower()}_config") or config.get("config", {})
        adapter_config = adapter_specific.copy()  # Make a copy to avoid modifying original
        
        # If no roster_service provided, try to get singleton instance via DI
        if roster_service is None:
            try:
                from api.dependencies import get_roster_service
                roster_service = get_roster_service()
                logging.info("AdapterFactory: using singleton roster_service via DI")
            except Exception:
                roster_service = None
               
        if adapter_type == "insightface":
            from recognition.adapters.cvlface_insight_adapter import CVLFaceInsightAdapter
            # Resolve device specification
            resolved_device = AdapterFactory._resolve_device("Entity identifier", adapter_config)
            model_path = adapter_config.get("model_path", None)
            return CVLFaceInsightAdapter(
                model_path=model_path,
                device=resolved_device,
                config=adapter_config,
                roster_service=roster_service
            )
        elif adapter_type == "adaface":
            # Use get_hf_pipeline() from pipeline_manager for AdaFace functionality
            from recognition.pipelines.pipeline_manager import get_hf_pipeline
            logging.info("Using CVLFace AdaFace pipeline via pipeline_manager")
            return get_hf_pipeline(roster_service=roster_service)
        elif adapter_type == "stub":
            from recognition.adapters.face_identification_adapter import FaceIdentificationAdapter
            logging.info("Using stub FaceIdentificationAdapter")
            return FaceIdentificationAdapter()
        else:
            from recognition.adapters.face_identification_adapter import FaceIdentificationAdapter
            logging.warning(f"Unknown entity identifier type '{adapter_type}', using stub implementation")
            return FaceIdentificationAdapter()
    
    @staticmethod
    def _create_caption_generator(config: Dict[str, Any]) -> ICaptionGeneration:
        adapter_type = config.get("type")
        adapter_config = config.get("config", {})
        
        # Mock adapter does not require a model_id
        if adapter_type == "mock":
            from analysis.adapters.mock_caption_adapter import MockCaptionAdapter
            logging.info("Using MockCaptionAdapter")
            return MockCaptionAdapter()
        
        # For other adapters, require model_id
        model_id = adapter_config.get("model_id")
        if not model_id:
            raise ValueError("model_id must be specified in configuration for caption generation")
        
        # Resolve device specification
        resolved_device = AdapterFactory._resolve_device("Caption generator", adapter_config)
        
        if adapter_type == "phi3":
            from analysis.adapters.phi3_caption_adapter import Phi3CaptionAdapter
            return Phi3CaptionAdapter(
                model_id=model_id,
                device=resolved_device,
                config=adapter_config
            )
        else:
            raise ValueError(f"Unsupported caption generation adapter type: {adapter_type}")
    
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
    
    @staticmethod
    def create_face_detector(config: Dict[str, Any]) -> Optional[IFaceDetection]:
        """
        Create and return a face detection adapter based on configuration.
        Returns None if no face detector is configured.
        """
        if not config:
            return None
            
        adapter_type = config.get('type')
        adapter_cfg = config.get('config', {})
        
        # Handle case where face detector is not configured or is mock
        if not adapter_type or adapter_type == 'mock':
            return None
        
        resolved_device = AdapterFactory._resolve_device('Face Detector', adapter_cfg)
        
        if adapter_type == 'yoloface':
            from recognition.adapters.yoloface_adapter import YoloFaceAdapter
            return YoloFaceAdapter(
                model_path=adapter_cfg.get('model_path'),
                device=resolved_device,
                config=adapter_cfg
            )
        elif adapter_type == 'mtcnn':
            from recognition.adapters.mtcnn_adapter import MTCNNAdapter
            return MTCNNAdapter(
                model_path=adapter_cfg.get('model_path'),
                device=resolved_device,
                config=adapter_cfg
            )
        else:
            raise ValueError(f"Unsupported face detector type: {adapter_type}")
    
    @staticmethod
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
    def create_entity_identifiers(config: Dict[str, Any], roster_service=None) -> List[RecognitionPort]:
        """
        Create multiple entity identifier adapters based on configuration.
        This supports the registry pattern for SceneComposer.
        """
        adapters = []
        
        # Create primary entity identifier - check both locations for entity_identifier config
        entity_identifier_config = config.get("entity_identifier")
        if not entity_identifier_config:
            # Fallback to adapters section
            adapters_config = config.get("adapters", {})
            entity_identifier_config = adapters_config.get("entity_identifier", {})
        
        primary_adapter = AdapterFactory._create_entity_identifier(entity_identifier_config, roster_service)
        adapters.append(primary_adapter)
        
        return adapters

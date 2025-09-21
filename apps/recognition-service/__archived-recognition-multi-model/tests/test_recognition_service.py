"""
Recognition Service Test Suite
Basic tests for the recognition service.
"""
import pytest
import numpy as np
from PIL import Image
import tempfile
import json
from pathlib import Path

from recognition.domain import (
    ModelType, AlignmentStrategy, FaceDetection, FaceEmbedding,
    RecognitionMatch, RecognitionResult, SceneAnalysisResult
)
from recognition.adapters import (
    FaceAlignerImpl, QualityScorerImpl, EmbeddingRouterImpl
)


class TestDomainEntities:
    """Test domain entities."""
    
    def test_face_detection_creation(self):
        """Test face detection creation."""
        detection = FaceDetection(
            bbox=[10, 20, 100, 120],
            confidence=0.95,
            landmarks=[[30, 40], [70, 40], [50, 60], [35, 80], [65, 80]]
        )
        
        assert detection.bbox == [10, 20, 100, 120]
        assert detection.confidence == 0.95
        assert len(detection.landmarks) == 5
    
    def test_face_embedding_creation(self):
        """Test face embedding creation."""
        embedding = FaceEmbedding(
            embedding=np.random.rand(512),
            confidence=0.9,
            quality_score=0.8,
            model_type=ModelType.ADAFACE_IR101
        )
        
        assert embedding.embedding.shape == (512,)
        assert embedding.confidence == 0.9
        assert embedding.quality_score == 0.8
        assert embedding.model_type == ModelType.ADAFACE_IR101
    
    def test_recognition_match_creation(self):
        """Test recognition match creation."""
        match = RecognitionMatch(
            person_name="John Doe",
            confidence=0.85,
            distance=0.15
        )
        
        assert match.person_name == "John Doe"
        assert match.confidence == 0.85
        assert match.distance == 0.15
    
    def test_scene_analysis_result_creation(self):
        """Test scene analysis result creation."""
        detection = FaceDetection(bbox=[10, 20, 100, 120], confidence=0.95)
        embedding = FaceEmbedding(embedding=np.random.rand(512), confidence=0.9)
        match = RecognitionMatch(person_name="John Doe", confidence=0.85, distance=0.15)
        
        face_result = RecognitionResult(
            detection=detection,
            embedding=embedding,
            matches=[match]
        )
        
        scene_result = SceneAnalysisResult(
            faces=[face_result],
            model_type=ModelType.ADAFACE_IR101,
            threshold=0.5,
            processing_time_ms=150.0
        )
        
        assert scene_result.total_faces == 1
        assert scene_result.identified_faces == 1
        assert scene_result.model_type == ModelType.ADAFACE_IR101
        assert scene_result.threshold == 0.5


class TestFaceAlignerImpl:
    """Test face aligner implementation."""
    
    def test_face_aligner_initialization(self):
        """Test face aligner initialization."""
        aligner = FaceAlignerImpl()
        assert aligner is not None
    
    def test_basic_alignment(self):
        """Test basic face alignment."""
        aligner = FaceAlignerImpl()
        
        # Create a test image
        test_image = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        
        # Create a test detection
        detection = FaceDetection(
            bbox=[50, 50, 100, 100],
            confidence=0.9
        )
        
        # Test alignment
        aligned_face = aligner.align_face(test_image, detection)
        
        assert aligned_face is not None
        assert aligned_face.shape == (112, 112, 3)
    
    def test_pil_image_input(self):
        """Test alignment with PIL image input."""
        aligner = FaceAlignerImpl()
        
        # Create PIL image
        test_image = Image.fromarray(np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8))
        
        detection = FaceDetection(
            bbox=[50, 50, 100, 100],
            confidence=0.9
        )
        
        aligned_face = aligner.align_face(test_image, detection)
        
        assert aligned_face is not None
        assert aligned_face.shape == (112, 112, 3)


class TestQualityScorerImpl:
    """Test quality scorer implementation."""
    
    def test_quality_scorer_initialization(self):
        """Test quality scorer initialization."""
        scorer = QualityScorerImpl()
        assert scorer is not None
    
    def test_quality_calculation(self):
        """Test quality score calculation."""
        scorer = QualityScorerImpl()
        
        # Create test face image
        face_image = np.random.randint(0, 255, (112, 112, 3), dtype=np.uint8)
        
        # Calculate quality
        quality_score = scorer.calculate_quality(face_image)
        
        assert isinstance(quality_score, float)
        assert 0.0 <= quality_score <= 1.0
    
    def test_quality_with_embedding(self):
        """Test quality calculation with embedding."""
        scorer = QualityScorerImpl()
        
        face_image = np.random.randint(0, 255, (112, 112, 3), dtype=np.uint8)
        embedding = np.random.rand(512)
        
        quality_score = scorer.calculate_quality(face_image, embedding)
        
        assert isinstance(quality_score, float)
        assert 0.0 <= quality_score <= 1.0


class TestEmbeddingRouterImpl:
    """Test embedding router implementation."""
    
    def test_embedding_router_initialization(self):
        """Test embedding router initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            router = EmbeddingRouterImpl(roster_dir=temp_dir)
            assert router is not None
    
    def test_empty_embeddings(self):
        """Test router with no embedding files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            router = EmbeddingRouterImpl(roster_dir=temp_dir)
            
            embeddings = router.get_embeddings(ModelType.ADAFACE_IR101)
            assert embeddings == {}
    
    def test_embedding_loading(self):
        """Test embedding loading from file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test embedding file
            embedding_data = {
                "John Doe": {
                    "embedding": np.random.rand(512).tolist(),
                    "model_type": "adaface_ir101",
                    "embedding_dim": 512
                },
                "Jane Smith": {
                    "embedding": np.random.rand(512).tolist(),
                    "model_type": "adaface_ir101", 
                    "embedding_dim": 512
                }
            }
            
            embedding_file = Path(temp_dir) / "adaface_ir101_embeddings.json"
            with open(embedding_file, 'w') as f:
                json.dump(embedding_data, f)
            
            # Test loading
            router = EmbeddingRouterImpl(roster_dir=temp_dir)
            embeddings = router.get_embeddings(ModelType.ADAFACE_IR101)
            
            assert len(embeddings) == 2
            assert "John Doe" in embeddings
            assert "Jane Smith" in embeddings
            assert embeddings["John Doe"].shape == (512,)
    
    def test_embedding_stats(self):
        """Test embedding statistics."""
        with tempfile.TemporaryDirectory() as temp_dir:
            router = EmbeddingRouterImpl(roster_dir=temp_dir)
            stats = router.get_embedding_stats()
            
            assert isinstance(stats, dict)
            assert ModelType.ADAFACE_IR101.value in stats
            assert stats[ModelType.ADAFACE_IR101.value]['count'] == 0


# Integration Tests
class TestServiceIntegration:
    """Test service integration."""
    
    def test_config_loading(self):
        """Test configuration loading."""
        from recognition.config import get_config
        
        config = get_config()
        assert config is not None
        
        service_config = config.get_service_config()
        assert service_config.get('name') == 'face-recognition-service'
    
    def test_pipeline_manager_compatibility(self):
        """Test pipeline manager backward compatibility."""
        from recognition.pipelines import get_hf_pipeline, clear_pipeline_cache
        
        # This should not raise an error
        pipeline = get_hf_pipeline()
        assert pipeline is not None
        
        # Clear cache should not raise an error
        clear_pipeline_cache()


if __name__ == "__main__":
    pytest.main([__file__])

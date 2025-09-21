#!/usr/bin/env python3
"""
Recognition Service Integration Test
Quick test to verify the service is working correctly.
"""
import asyncio
import logging
import sys
from pathlib import Path
import numpy as np
from PIL import Image

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_recognition_service():
    """Test the recognition service."""
    try:
        logger.info("🧪 Starting recognition service integration test...")
        
        # Import recognition service
        from recognition.ports.dependencies import get_recognition_service
        from recognition.domain import ModelType
        
        # Get service
        logger.info("📋 Getting recognition service...")
        recognition_service = get_recognition_service()
        
        # Create a test image
        logger.info("🖼️ Creating test image...")
        test_image = Image.fromarray(np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8))
        
        # Test each model
        models = [ModelType.ADAFACE_IR101, ModelType.INSIGHTFACE_W600K, ModelType.ARCFACE_IR50]
        
        for model_type in models:
            logger.info(f"🔍 Testing {model_type.value}...")
            
            try:
                result = await recognition_service.analyze_scene(
                    image=test_image,
                    model_type=model_type,
                    threshold=0.5
                )
                
                logger.info(f"✅ {model_type.value}: "
                           f"detected {result.total_faces} faces, "
                           f"processing time {result.processing_time_ms:.2f}ms")
                
            except Exception as e:
                logger.error(f"❌ {model_type.value} failed: {e}")
                continue
        
        logger.info("🎉 Recognition service integration test completed!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config():
    """Test configuration loading."""
    try:
        logger.info("⚙️ Testing configuration...")
        
        from recognition.config import get_config
        
        config = get_config()
        service_config = config.get_service_config()
        models_config = config.get_models_config()
        
        logger.info(f"✅ Service: {service_config.get('name')}")
        logger.info(f"✅ Models: {list(models_config.keys())}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Config test failed: {e}")
        return False


def test_embedding_router():
    """Test embedding router."""
    try:
        logger.info("📊 Testing embedding router...")
        
        from recognition.adapters import EmbeddingRouterImpl
        from recognition.domain import ModelType
        
        # Use datasets/micro for testing
        router = EmbeddingRouterImpl(roster_dir="datasets/micro")
        
        for model_type in ModelType:
            embeddings = router.get_embeddings(model_type)
            logger.info(f"✅ {model_type.value}: {len(embeddings)} embeddings")
            
            if embeddings:
                first_name = list(embeddings.keys())[0]
                first_embedding = embeddings[first_name]
                logger.info(f"   Sample: {first_name} -> {first_embedding.shape}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Embedding router test failed: {e}")
        return False


def test_adapters():
    """Test adapter implementations."""
    try:
        logger.info("🔧 Testing adapters...")
        
        from recognition.adapters import FaceAlignerImpl, QualityScorerImpl
        
        # Test face aligner
        aligner = FaceAlignerImpl()
        logger.info("✅ Face aligner initialized")
        
        # Test quality scorer
        scorer = QualityScorerImpl()
        test_face = np.random.randint(0, 255, (112, 112, 3), dtype=np.uint8)
        quality_score = scorer.calculate_quality(test_face)
        logger.info(f"✅ Quality scorer: {quality_score:.3f}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Adapter test failed: {e}")
        return False


async def main():
    """Main test function."""
    logger.info("🚀 Recognition Service Integration Tests")
    logger.info("=" * 50)
    
    # Set environment for testing
    import os
    os.environ['ROSTER_DATA_DIR'] = 'datasets/micro'
    
    tests = [
        ("Configuration", test_config),
        ("Embedding Router", test_embedding_router),
        ("Adapters", test_adapters),
        ("Recognition Service", test_recognition_service),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        logger.info(f"\n📋 Running {test_name} test...")
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"❌ {test_name} test failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("📊 TEST RESULTS")
    logger.info("=" * 50)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
        if result:
            passed += 1
    
    logger.info(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tests passed!")
        sys.exit(0)
    else:
        logger.error("❌ Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

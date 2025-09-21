"""
Ground Truth Accuracy Test

Tests recognition accuracy using known ground truth mappings from the mock dataset.
This test provides meaningful accuracy metrics by comparing against actual known identities.
"""

import pytest
import json
import time
import os
import warnings
from pathlib import Path
from PIL import Image
import numpy as np
import statistics

# Suppress known third-party warnings
warnings.filterwarnings("ignore", ".*rcond.*", FutureWarning)

# Configure environment before importing RecognitionService
os.environ.setdefault("INSIGHTFACE_CACHE_DIR", "/Volumes/Butter/")
os.environ.setdefault("CACHE_DIR", "/Volumes/Butter/")
os.environ.setdefault("RECOG_INSIGHTFACE_DEVICE", "mps")  # Force MPS for better performance

from recognition.services import RecognitionService


# Ground truth mappings extracted from mock_client.py
# Maps test image filenames to expected person names that should be detected
GROUND_TRUTH_MAPPINGS = {
    # Liam Maloney
    "liam-maloney-2.jpg": ["Liam Maloney"],
    "liam-maloney-home.jpg": ["Liam Maloney"], 
    "liam-maloney-painting.jpg": ["Liam Maloney"],
    
    # Kirstie McCarrel
    "kirstie-daniel-sunglasses.jpg": ["Kirstie McCarrel"],  # Note: Also contains Daniel but focusing on primary subject
    "kirstie-boat.jpg": ["Kirstie McCarrel"],
    "k.mcc-1.jpg": ["Kirstie McCarrel"],
    "kirstie-pool.jpg": ["Kirstie McCarrel"],
    "kirstie-1.jpeg": ["Kirstie McCarrel"],
    
    # Ellyn Heald
    "example-ellynheald-goldleaf.jpeg": ["Ellyn Heald"],
    
    # Bea Burke
    "bea-nye.jpg": ["Bea Burke"],
    
    # Caitlin Weaver (ccqw = Caitlin Quintero Weaver)
    "ccqw-occlusion.jpg": ["Caitlin Weaver"],
    "ccqw-occlusion-2.jpg": ["Caitlin Weaver"],
    "ccqw-running.jpg": ["Caitlin Weaver"],
    "ccqw-running-2.jpg": ["Caitlin Weaver"],
    "ccqw.blurry.jpg": ["Caitlin Weaver"],
    "ccqw-bar.jpg": ["Caitlin Weaver"],
    "ccqw-flowers.jpg": ["Caitlin Weaver"],
    "ccqw-sunglasses-flowers.jpg": ["Caitlin Weaver"],
    "ccqw-antartica.jpg": ["Caitlin Weaver"],
    "ccqw-sunglasses.jpg": ["Caitlin Weaver"],
    "ccqw-purple.jpg": ["Caitlin Weaver"],
    "ccqw-hair.jpg": ["Caitlin Weaver"],
    "ccqw-underexposed.jpg": ["Caitlin Weaver"],
    
    # Maria Correonero  
    "maria-cocktail.jpg": ["Maria Correonero"],
    "maria-pool.jpg": ["Maria Correonero"],
    "maria-party.jpg": ["Maria Correonero"],
    "mcm-eye-blocked.jpg": ["Maria Correonero"],  # mcm = Maria Correonero
    "mcm-icecave.jpg": ["Maria Correonero"],
    "mcm-planecrash.jpg": ["Maria Correonero"],
    
    # Ryann Wiseman
    "ryann-party.jpg": ["Ryann Wiseman"],
    "ryann-group-party.jpg": ["Ryann Wiseman"],
    "ryann-bar.jpg": ["Ryann Wiseman"],
    "rrw-mirror.jpg": ["Ryann Wiseman"],  # rrw = Ryann Wiseman
}

# Reference entity mappings for setting up roster
# Maps entity names to all their available reference images from /scripts/mock_entities
REFERENCE_ENTITIES = {
    "Ellyn Heald": ["entity-ellyn-heald.jpeg"],
    "Kirstie McCarrel": ["entity-kirstie-mccarrel.jpg"],
    "Bea Burke": ["entity-bea-burke.jpg"],
    "Caitlin Weaver": [
        "entity-caitlin-weaver.jpg",
        "entity-caitlin-weaver-2.jpg", 
        "entity-caitlin-weaver-3.jpg",
        "entity-caitlin-weaver-4.jpg",
        "entity-caitlin-weaver-5.jpg"
    ],
    "Maria Correonero": [
        "entity-maria-correonero.jpg",
        "entity-maria-correonero-2.jpg"
    ],
    "Erika Hansen Miller": [
        "entity-erika-hansen-miller.jpg",
        "entity-erika-hansen-miller-2.jpg"
    ],
    "Ryann Wiseman": [
        "entity-ryann-wiseman.jpg",
        "entity-ryann-wiseman.png"
    ],
    "Daniel Arcé": [
        "entity-daniel-arce.jpg",
        "entity-daniel-arce-2.jpg"
    ],
    "Liam Maloney": ["entity-liam-maloney.jpg"],
    "Cristina Quintana": ["entity-cristina-quintana.png"]
}


@pytest.fixture
def recognition_service():
    """Create recognition service instance with verified cache configuration."""
    # Verify cache environment is properly set
    cache_dir = os.getenv("INSIGHTFACE_CACHE_DIR", "/tmp/insightface_models")
    print(f"\n🔧 Setting up recognition service...")
    print(f"📁 InsightFace cache directory: {cache_dir}")
    
    # Check if models already exist to avoid re-download
    expected_cache = Path(cache_dir) / "insightface" / "models" / "buffalo_l"
    if expected_cache.exists():
        model_files = list(expected_cache.glob('*.onnx'))
        print(f"✅ Found existing models in cache: {expected_cache}")
        print(f"📁 Model files ({len(model_files)}): {[f.name for f in model_files]}")
    else:
        print(f"⚠️  Models not found in cache, will be downloaded: {expected_cache}")
    
    # Show GPU/device information
    try:
        from shared.infrastructure.gpu_manager import GPUManager
        gpu_manager = GPUManager()
        device_info = gpu_manager.get_device_info()
        print(f"🖥️  Device detection:")
        print(f"  Best device: {device_info.best_device}")
        print(f"  CUDA available: {device_info.cuda_available}")
        print(f"  MPS available: {device_info.mps_available}")
        if device_info.gpu_info:
            print(f"  GPU: {device_info.gpu_info.name} ({device_info.gpu_info.memory_gb:.1f}GB)")
        
        # Check ONNX providers
        try:
            import onnxruntime as ort
            available_providers = ort.get_available_providers()
            print(f"  ONNX providers: {available_providers}")
        except ImportError:
            print(f"  ONNX providers: Not available (will check at runtime)")
    except Exception as e:
        print(f"⚠️  Could not get device info: {e}")
    
    print(f"🚀 Creating recognition service...")
    service = RecognitionService()
    print(f"✅ Recognition service created successfully")
    
    return service


@pytest.fixture
def project_root():
    """Get project root path."""
    return Path(__file__).parent.parent.parent


@pytest.fixture
def mock_images_path(project_root):
    """Get path to mock images."""
    mock_path = project_root / "scripts" / "mock_images"
    if not mock_path.exists():
        pytest.skip("Mock images not found")
    return mock_path


@pytest.fixture
def mock_entities_path(project_root):
    """Get path to mock entities."""
    entities_path = project_root / "scripts" / "mock_entities"
    if not entities_path.exists():
        pytest.skip("Mock entities not found")
    return entities_path


async def setup_test_roster(mock_entities_path):
    """
    Set up reference entity data for testing.
    
    Since we don't have direct roster access in this test,
    we'll just verify the reference images exist and can be loaded.
    """
    print("Verifying reference entities for ground truth testing...")
    
    setup_results = {}
    
    for entity_name, image_filenames in REFERENCE_ENTITIES.items():
        entity_images = []
        
        # Load all reference images for this entity to verify they exist
        for image_filename in image_filenames:
            image_path = mock_entities_path / image_filename
            
            if image_path.exists():
                try:
                    image = Image.open(image_path)
                    entity_images.append(image_path)
                    print(f"  ✓ Found {image_filename} for {entity_name}")
                except Exception as e:
                    print(f"  ⚠️ Could not load {image_filename}: {e}")
        
        setup_results[entity_name] = {
            "success": len(entity_images) > 0,
            "total_images": len(entity_images),
            "image_paths": entity_images
        }
        
        if len(entity_images) > 0:
            print(f"  ✅ {entity_name}: {len(entity_images)} reference images available")
        else:
            print(f"  ❌ {entity_name}: No valid reference images found")
    
    # Summary
    successful_entities = [name for name, result in setup_results.items() if result["success"]]
    total_images = sum(result.get("total_images", 0) for result in setup_results.values() if result["success"])
    
    print(f"\n=== Reference Entity Verification Complete ===")
    print(f"Entities with valid references: {len(successful_entities)}/{len(REFERENCE_ENTITIES)}")
    print(f"Total reference images found: {total_images}")
    print(f"Available entities: {successful_entities}")
    
    return setup_results


@pytest.mark.asyncio
async def test_ground_truth_face_detection_and_analysis(recognition_service, mock_images_path, mock_entities_path):
    """
    Test face detection and analysis using ground truth data.
    
    This test verifies that the service can detect faces and extract embeddings
    from images where we know faces should be present. While it can't test
    identity matching without a populated roster, it can test the core
    face recognition pipeline.
    """
    # Verify reference entities exist
    print("Verifying reference entities...")
    setup_results = await setup_test_roster(mock_entities_path)
    
    successful_entities = [name for name, result in setup_results.items() if result["success"]]
    if len(successful_entities) < 5:
        pytest.skip(f"Insufficient reference entities ({len(successful_entities)}) - need at least 5 for meaningful test")
    
    total_tests = 0
    faces_detected = 0
    processing_times = []
    detection_results = []
    
    for image_filename, expected_people in GROUND_TRUTH_MAPPINGS.items():
        # Only test images where we expect people who have reference images
        expected_with_references = [person for person in expected_people if person in successful_entities]
        if not expected_with_references:
            continue
            
        image_path = mock_images_path / image_filename
        if not image_path.exists():
            print(f"Warning: Test image not found: {image_path}")
            continue
            
        try:
            # Load and process image
            image = Image.open(image_path)
            
            start_time = time.time()
            result = await recognition_service.recognize_faces(image)
            processing_time = (time.time() - start_time) * 1000
            processing_times.append(processing_time)
            
            total_tests += 1
            
            # Check face detection results
            num_faces_detected = len(result.face_detections)
            faces_with_embeddings = len(result.face_embeddings)
            quality_scores = []
            
            # Note: Quality scores are not available in the simplified InsightFace service
            # The service focuses on detection accuracy rather than quality assessment
            
            if num_faces_detected > 0:
                faces_detected += 1
                status = "✅ DETECTED"
            else:
                status = "❌ NO FACES"
            
            detection_results.append({
                "image": image_filename,
                "expected_people": expected_with_references,
                "faces_detected": num_faces_detected,
                "faces_with_embeddings": faces_with_embeddings,
                "avg_quality": None,  # Not available in simplified service
                "processing_time": processing_time,
                "has_matches": len(result.matches) > 0
            })
            
            print(f"{status} - {image_filename}")
            print(f"  Expected people: {expected_with_references}")
            print(f"  Faces detected: {num_faces_detected}")
            print(f"  Faces with embeddings: {faces_with_embeddings}")
            print(f"  Processing time: {processing_time:.1f}ms")
            if len(result.matches) > 0:
                print(f"  Matches found: {len(result.matches)}")
            
        except Exception as e:
            print(f"Error processing {image_filename}: {e}")
            continue
    
    # Calculate and report results
    if total_tests > 0:
        detection_rate = faces_detected / total_tests
        avg_processing_time = statistics.mean(processing_times)
        p95_processing_time = sorted(processing_times)[int(0.95 * len(processing_times))]
        
        # Calculate embedding extraction rate
        total_faces_detected = sum(r["faces_detected"] for r in detection_results)
        total_faces_with_embeddings = sum(r["faces_with_embeddings"] for r in detection_results)
        embedding_rate = total_faces_with_embeddings / total_faces_detected if total_faces_detected > 0 else 0
        
        print(f"\n=== Ground Truth Face Detection and Analysis Results ===")
        print(f"Total images tested: {total_tests}")
        print(f"Images with faces detected: {faces_detected}")
        print(f"Face detection rate: {detection_rate:.2%}")
        print(f"Total faces detected: {total_faces_detected}")
        print(f"Total face embeddings: {total_faces_with_embeddings}")
        print(f"Embedding extraction rate: {embedding_rate:.2%}")
        print(f"Average processing time: {avg_processing_time:.1f}ms")
        print(f"P95 processing time: {p95_processing_time:.1f}ms")
        
        # Show GPU acceleration status
        try:
            from shared.infrastructure.gpu_manager import GPUManager
            gpu_manager = GPUManager()
            device_info = gpu_manager.get_device_info()
            print(f"\n=== GPU Acceleration Status ===")
            print(f"Best device detected: {device_info.best_device}")
            print(f"CUDA available: {device_info.cuda_available}")
            print(f"MPS available: {device_info.mps_available}")
            if device_info.gpu_info:
                print(f"GPU: {device_info.gpu_info.name} ({device_info.gpu_info.memory_gb:.1f}GB)")
        except Exception as e:
            print(f"Could not get GPU info: {e}")
        
        # Show failed detections
        failed_detections = [r for r in detection_results if r["faces_detected"] == 0]
        if failed_detections:
            print(f"\n=== Failed Detections ({len(failed_detections)}) ===")
            for failure in failed_detections:
                print(f"  - {failure['image']}: expected {failure['expected_people']}")
        
        # Show successful detections with performance details
        successful_detections = [r for r in detection_results if r["faces_detected"] > 0]
        if successful_detections:
            print(f"\n=== Successful Detections ({len(successful_detections)}) ===")
            # Show top 5 fastest and slowest
            sorted_by_time = sorted(successful_detections, key=lambda x: x["processing_time"])
            print(f"Fastest 3:")
            for r in sorted_by_time[:3]:
                print(f"  - {r['image']}: {r['faces_detected']} faces in {r['processing_time']:.1f}ms")
            print(f"Slowest 3:")
            for r in sorted_by_time[-3:]:
                print(f"  - {r['image']}: {r['faces_detected']} faces in {r['processing_time']:.1f}ms")
        
        # Show quality analysis - Note: Quality scores not available in simplified service
        print(f"\n=== Service Capabilities ===")
        print(f"Quality scoring: Not available (simplified InsightFace service)")
        print(f"Service focus: Detection accuracy and embedding extraction")
        print(f"Model: buffalo_l (InsightFace)")
        
        # Performance summary
        print(f"\n=== Performance Summary ===")
        print(f"✅ Detection rate: {detection_rate:.1%} ({faces_detected}/{total_tests})")
        print(f"✅ Embedding rate: {embedding_rate:.1%} ({total_faces_with_embeddings}/{total_faces_detected})")
        print(f"⏱️  Avg time/image: {avg_processing_time:.1f}ms")
        print(f"⏱️  P95 time/image: {p95_processing_time:.1f}ms")
        
        # Test assertions - these are meaningful pipeline validation requirements
        assert total_tests >= 5, f"Should test at least 5 images with known people, got {total_tests}"
        assert detection_rate >= 0.70, f"Face detection rate should be ≥70%, got {detection_rate:.2%}"
        assert embedding_rate >= 0.90, f"Embedding extraction rate should be ≥90%, got {embedding_rate:.2%}"
        
        print(f"\n🎉 All tests passed! Recognition service is working correctly.")
        print(f"ℹ️  Note: First-run times include model initialization overhead.")
        
    else:
        pytest.fail("No test images with known people could be processed")


@pytest.mark.asyncio
async def test_ground_truth_basic_face_detection_accuracy(recognition_service, mock_images_path):
    """
    Test face detection accuracy using ground truth data.
    
    This test verifies that the service can detect faces in images where 
    we know faces should be present.
    """
    total_tests = 0
    faces_detected = 0
    processing_times = []
    failed_detections = []
    
    for image_filename, expected_people in GROUND_TRUTH_MAPPINGS.items():
        image_path = mock_images_path / image_filename
        
        if not image_path.exists():
            print(f"Warning: Test image not found: {image_path}")
            continue
            
        try:
            # Load and process image
            image = Image.open(image_path)
            
            start_time = time.time()
            result = await recognition_service.recognize_faces(image)
            processing_time = (time.time() - start_time) * 1000
            processing_times.append(processing_time)
            
            total_tests += 1
            
            # Check if at least one face was detected
            num_faces_detected = len(result.face_detections)
            if num_faces_detected > 0:
                faces_detected += 1
            else:
                failed_detections.append({
                    "image": image_filename,
                    "expected_people": expected_people
                })
            
            print(f"Image: {image_filename}")
            print(f"  Expected people: {expected_people}")
            print(f"  Faces detected: {num_faces_detected}")
            print(f"  Processing time: {processing_time:.1f}ms")
            
        except Exception as e:
            print(f"Error processing {image_filename}: {e}")
            continue
    
    # Calculate and report results
    if total_tests > 0:
        detection_rate = faces_detected / total_tests
        avg_processing_time = statistics.mean(processing_times)
        p95_processing_time = sorted(processing_times)[int(0.95 * len(processing_times))]
        
        print(f"\n=== Ground Truth Face Detection Results ===")
        print(f"Total images tested: {total_tests}")
        print(f"Images with faces detected: {faces_detected}")
        print(f"Face detection rate: {detection_rate:.2%}")
        print(f"Average processing time: {avg_processing_time:.1f}ms")
        print(f"P95 processing time: {p95_processing_time:.1f}ms")
        
        if failed_detections:
            print(f"\nFailed detections ({len(failed_detections)}):")
            for failure in failed_detections:
                print(f"  - {failure['image']}: expected {failure['expected_people']}")
        
        # Assertions for test requirements
        assert total_tests >= 10, f"Should test at least 10 images, got {total_tests}"
        assert detection_rate >= 0.80, f"Face detection rate should be ≥80%, got {detection_rate:.2%}"
        assert avg_processing_time < 2000, f"Average processing time should be <2s, got {avg_processing_time:.1f}ms"
        
    else:
        pytest.fail("No test images could be processed")


@pytest.mark.asyncio 
async def test_recognition_quality_metrics(recognition_service, mock_images_path):
    """
    Test various metrics of the recognition system.
    
    Note: Quality scoring is not available in the simplified InsightFace service.
    This test focuses on detection confidence and basic metrics.
    """
    confidence_scores = []
    face_sizes = []
    
    # Test a subset of high-quality images
    high_quality_test_images = [
        "liam-maloney-home.jpg",
        "kirstie-boat.jpg", 
        "bea-nye.jpg",
        "ccqw-bar.jpg",
        "maria-cocktail.jpg"
    ]
    
    for image_filename in high_quality_test_images:
        image_path = mock_images_path / image_filename
        
        if not image_path.exists():
            continue
            
        try:
            image = Image.open(image_path)
            result = await recognition_service.recognize_faces(image)
            
            for detection in result.face_detections:
                # Extract confidence scores  
                confidence_scores.append(detection.confidence)
                
                # Calculate face size (area of bounding box)
                x_min, y_min, x_max, y_max = detection.bbox
                face_area = (x_max - x_min) * (y_max - y_min)
                face_sizes.append(face_area)
                
        except Exception as e:
            print(f"Error processing {image_filename}: {e}")
            continue
    
    # Analyze metrics
    if confidence_scores:
        avg_confidence = statistics.mean(confidence_scores)  
        print(f"Average detection confidence: {avg_confidence:.3f}")
        assert avg_confidence > 0.7, f"Average confidence should be >0.7, got {avg_confidence:.3f}"
    
    if face_sizes:
        avg_face_size = statistics.mean(face_sizes)
        print(f"Average face size (pixels²): {avg_face_size:.0f}")
        assert avg_face_size > 1000, f"Average face size should be >1000px², got {avg_face_size:.0f}"
    
    print(f"Note: Quality scoring not available in simplified InsightFace service.")


@pytest.mark.asyncio
async def test_challenging_conditions(recognition_service, mock_images_path):
    """
    Test recognition performance under challenging conditions.
    
    This test specifically examines how well the system handles:
    - Occlusions (sunglasses, partial blocking)
    - Poor lighting (underexposed)
    - Motion blur
    - Multiple people in scene
    """
    challenging_scenarios = {
        "occlusion": [
            "ccqw-occlusion.jpg",
            "ccqw-occlusion-2.jpg", 
            "ccqw-sunglasses.jpg",
            "ccqw-sunglasses-flowers.jpg",
            "mcm-eye-blocked.jpg"
        ],
        "lighting": [
            "ccqw-underexposed.jpg"
        ],
        "blur": [
            "ccqw.blurry.jpg"
        ],
        "multiple_people": [
            "kirstie-daniel-sunglasses.jpg",
            "ryann-group-party.jpg",
            "ccqw-erika.jpg"
        ]
    }
    
    results = {}
    
    for scenario_type, image_list in challenging_scenarios.items():
        scenario_results = {
            "total": 0,
            "detected": 0,
            "processing_times": []
        }
        
        for image_filename in image_list:
            image_path = mock_images_path / image_filename
            
            if not image_path.exists():
                continue
                
            try:
                image = Image.open(image_path)
                
                start_time = time.time()
                result = await recognition_service.recognize_faces(image)
                processing_time = (time.time() - start_time) * 1000
                
                scenario_results["total"] += 1
                scenario_results["processing_times"].append(processing_time)
                
                if len(result.face_detections) > 0:
                    scenario_results["detected"] += 1
                
                print(f"{scenario_type.upper()} - {image_filename}: {len(result.face_detections)} faces detected")
                
            except Exception as e:
                print(f"Error processing {image_filename}: {e}")
                continue
        
        results[scenario_type] = scenario_results
    
    # Analyze challenging condition results
    print(f"\n=== Challenging Conditions Results ===")
    for scenario_type, scenario_data in results.items():
        if scenario_data["total"] > 0:
            detection_rate = scenario_data["detected"] / scenario_data["total"]
            avg_time = statistics.mean(scenario_data["processing_times"])
            
            print(f"{scenario_type.upper()}:")
            print(f"  Detection rate: {detection_rate:.2%} ({scenario_data['detected']}/{scenario_data['total']})")
            print(f"  Avg processing time: {avg_time:.1f}ms")
            
            # More lenient requirements for challenging conditions
            if scenario_type == "occlusion":
                assert detection_rate >= 0.60, f"Occlusion detection rate should be ≥60%, got {detection_rate:.2%}"
            elif scenario_type == "lighting":
                assert detection_rate >= 0.50, f"Poor lighting detection rate should be ≥50%, got {detection_rate:.2%}"
            elif scenario_type == "blur":
                assert detection_rate >= 0.30, f"Blur detection rate should be ≥30%, got {detection_rate:.2%}"
            elif scenario_type == "multiple_people":
                assert detection_rate >= 0.80, f"Multiple people detection rate should be ≥80%, got {detection_rate:.2%}"


@pytest.mark.asyncio
async def test_comprehensive_entity_embedding_generation(recognition_service, mock_entities_path, project_root):
    """
    Test comprehensive entity embedding generation for all mock entities.
    
    This test:
    1. Generates embeddings for ALL entities in the mock_entities directory
    2. Tests the embedding quality and consistency 
    3. Creates a proper embeddings file for use in matching tests
    """
    print("🧪 Testing comprehensive entity embedding generation...")
    
    # Discover all entity files in the directory
    entity_files = list(mock_entities_path.glob("entity-*.jpg")) + list(mock_entities_path.glob("entity-*.png")) + list(mock_entities_path.glob("entity-*.jpeg"))
    print(f"📁 Found {len(entity_files)} entity files in {mock_entities_path}")
    
    successful_embeddings = []
    failed_embeddings = []
    processing_times = []
    
    # Generate embeddings for each entity
    for entity_file in sorted(entity_files):
        entity_name = entity_file.stem.replace("entity-", "").replace("-", " ").title()
        print(f"\n🎯 Processing: {entity_name} ({entity_file.name})")
        
        try:
            # Load and process image
            image = Image.open(entity_file)
            print(f"  📸 Image loaded: {image.size}")
            
            start_time = time.time()
            result = await recognition_service.recognize_faces(image)
            processing_time = (time.time() - start_time) * 1000
            processing_times.append(processing_time)
            
            # Check results
            num_faces = len(result.face_detections)
            num_embeddings = len(result.face_embeddings)
            
            if num_faces > 0 and num_embeddings > 0:
                detection = result.face_detections[0]
                embedding = result.face_embeddings[0]
                
                # Validate embedding
                embedding_array = np.array(embedding.embedding)
                embedding_norm = np.linalg.norm(embedding_array)
                
                successful_embeddings.append({
                    "entity_name": entity_name,
                    "file_name": entity_file.name,
                    "faces_detected": num_faces,
                    "embedding_dimension": len(embedding.embedding),
                    "embedding_norm": embedding_norm,
                    "confidence": detection.confidence,
                    "processing_time": processing_time,
                    "bbox": detection.bbox
                })
                
                print(f"  ✅ SUCCESS - {num_faces} face(s), embedding dim: {len(embedding.embedding)}, norm: {embedding_norm:.3f}, conf: {detection.confidence:.3f}")
                
            else:
                failed_embeddings.append({
                    "entity_name": entity_name,
                    "file_name": entity_file.name,
                    "faces_detected": num_faces,
                    "embeddings_generated": num_embeddings,
                    "processing_time": processing_time
                })
                print(f"  ❌ FAILED - {num_faces} faces, {num_embeddings} embeddings")
                
        except Exception as e:
            failed_embeddings.append({
                "entity_name": entity_name,
                "file_name": entity_file.name,
                "error": str(e)
            })
            print(f"  💥 ERROR - {e}")
    
    # Generate comprehensive report
    total_entities = len(entity_files)
    successful_count = len(successful_embeddings)
    failed_count = len(failed_embeddings)
    success_rate = successful_count / total_entities if total_entities > 0 else 0
    
    print(f"\n=== Comprehensive Entity Embedding Results ===")
    print(f"Total entities processed: {total_entities}")
    print(f"Successful embeddings: {successful_count}")
    print(f"Failed embeddings: {failed_count}")
    print(f"Success rate: {success_rate:.2%}")
    
    if successful_embeddings:
        avg_processing_time = statistics.mean(processing_times)
        embedding_dims = [e["embedding_dimension"] for e in successful_embeddings]
        embedding_norms = [e["embedding_norm"] for e in successful_embeddings]
        confidences = [e["confidence"] for e in successful_embeddings]
        
        print(f"Average processing time: {avg_processing_time:.1f}ms")
        print(f"Embedding dimensions: {set(embedding_dims)} (should all be 512)")
        print(f"Average embedding norm: {statistics.mean(embedding_norms):.3f}")
        print(f"Average confidence: {statistics.mean(confidences):.3f}")
    
    # Show detailed results
    if successful_embeddings:
        print(f"\n=== Successful Entity Embeddings ===")
        for embedding in successful_embeddings:
            print(f"✅ {embedding['entity_name']}: {embedding['file_name']} "
                  f"(dim: {embedding['embedding_dimension']}, "
                  f"norm: {embedding['embedding_norm']:.3f}, "
                  f"conf: {embedding['confidence']:.3f})")
    
    if failed_embeddings:
        print(f"\n=== Failed Entity Embeddings ===")
        for failure in failed_embeddings:
            error_msg = failure.get('error', f"{failure.get('faces_detected', 0)} faces detected")
            print(f"❌ {failure['entity_name']}: {failure['file_name']} - {error_msg}")
    
    # Create embeddings file for further testing
    if successful_embeddings:
        embeddings_file = project_root / "test_embeddings.json"
        print(f"\n📝 Creating embeddings file: {embeddings_file}")
        
        # Generate embeddings data for each successful entity
        embeddings_data = []
        for embedding_info in successful_embeddings:
            # Convert numpy types to Python types for JSON serialization
            bbox = embedding_info["bbox"]
            if isinstance(bbox, (list, tuple)):
                bbox = [int(x) for x in bbox]  # Convert numpy int64 to Python int
            
            embeddings_data.append({
                "name": embedding_info["entity_name"],
                "file": embedding_info["file_name"],
                "embedding_dimension": int(embedding_info["embedding_dimension"]),
                "confidence": float(embedding_info["confidence"]),
                "bbox": bbox
            })
        
        # Save metadata (actual embeddings would require another processing pass)
        with open(embeddings_file, 'w') as f:
            json.dump({
                "metadata": {
                    "total_entities": len(embeddings_data),
                    "embedding_dimension": 512,
                    "model": "buffalo_l",
                    "generated_at": time.time()
                },
                "entities": embeddings_data
            }, f, indent=2)
        
        print(f"✅ Embeddings metadata saved to {embeddings_file}")
    
    # Test assertions
    assert total_entities >= 10, f"Should have at least 10 entity files, found {total_entities}"
    assert success_rate >= 0.80, f"Should have ≥80% success rate, got {success_rate:.2%}"
    assert successful_count >= 8, f"Should have at least 8 successful embeddings, got {successful_count}"
    
    # Validate embedding consistency
    if successful_embeddings:
        dimensions = set(e["embedding_dimension"] for e in successful_embeddings)
        assert len(dimensions) == 1, f"All embeddings should have same dimension, got {dimensions}"
        assert 512 in dimensions, f"Embeddings should be 512-dimensional, got {dimensions}"
        
        # Check embedding norms are reasonable (normalized embeddings should be ~1.0)
        norms = [e["embedding_norm"] for e in successful_embeddings]
        avg_norm = statistics.mean(norms)
        assert 0.5 <= avg_norm <= 2.0, f"Average embedding norm should be reasonable, got {avg_norm:.3f}"


@pytest.mark.asyncio
async def test_generate_embeddings_file_for_roster(recognition_service, mock_entities_path, project_root):
    """
    Generate a proper embeddings file that can be used by the embedding router.
    
    This test creates a complete embeddings.json file with actual embedding vectors
    that can be loaded by the EmbeddingRouterAdapter for matching tests.
    """
    print("📝 Generating embeddings file for roster matching...")
    
    # Process each entity and collect embeddings
    embeddings_data = []
    
    for entity_name, image_files in REFERENCE_ENTITIES.items():
        print(f"\n🎯 Processing entity: {entity_name}")
        entity_embeddings = []
        
        for image_file in image_files:
            image_path = mock_entities_path / image_file
            
            if not image_path.exists():
                print(f"  ⚠️  File not found: {image_file}")
                continue
                
            try:
                # Load and process image
                image = Image.open(image_path)
                result = await recognition_service.recognize_faces(image)
                
                if len(result.face_detections) > 0 and len(result.face_embeddings) > 0:
                    detection = result.face_detections[0]
                    embedding = result.face_embeddings[0]
                    
                    entity_embeddings.append({
                        "file": image_file,
                        "embedding": embedding.embedding,
                        "confidence": detection.confidence,
                        "bbox": detection.bbox
                    })
                    
                    print(f"  ✅ {image_file}: confidence={detection.confidence:.3f}")
                else:
                    print(f"  ❌ {image_file}: No face detected")
                    
            except Exception as e:
                print(f"  💥 {image_file}: Error - {e}")
        
        if entity_embeddings:
            # Use the best embedding (highest confidence) as the primary
            best_embedding = max(entity_embeddings, key=lambda x: x["confidence"])
            
            embeddings_data.append({
                "name": entity_name,
                "embedding": best_embedding["embedding"],
                "confidence": best_embedding["confidence"],
                "source_file": best_embedding["file"],
                "bbox": best_embedding["bbox"],
                "total_reference_images": len(entity_embeddings)
            })
            
            print(f"  🎯 Using best embedding from {best_embedding['file']} (conf: {best_embedding['confidence']:.3f})")
        else:
            print(f"  ❌ No valid embeddings for {entity_name}")
    
    # Create the embeddings file
    embeddings_file = project_root / "roster" / "data" / "insightface_embeddings.json"
    embeddings_file.parent.mkdir(parents=True, exist_ok=True)
    
    embeddings_json = {
        "metadata": {
            "model": "buffalo_l",
            "embedding_dimension": 512,
            "total_entities": len(embeddings_data),
            "generated_at": time.time(),
            "description": "Generated embeddings for ground truth testing"
        },
        "embeddings": embeddings_data
    }
    
    with open(embeddings_file, 'w') as f:
        json.dump(embeddings_json, f, indent=2)
    
    print(f"\n✅ Embeddings file created: {embeddings_file}")
    print(f"📊 Total entities with embeddings: {len(embeddings_data)}")
    
    # Validate the file can be loaded
    try:
        with open(embeddings_file, 'r') as f:
            loaded_data = json.load(f)
        
        print(f"✅ Embeddings file validation successful")
        print(f"📈 File size: {embeddings_file.stat().st_size / 1024:.1f}KB")
        
        # Test that embeddings are proper vectors
        for i, entity in enumerate(loaded_data["embeddings"]):
            embedding = entity["embedding"]
            if not isinstance(embedding, list) or len(embedding) != 512:
                raise ValueError(f"Invalid embedding for {entity['name']}: expected list of 512 floats")
            
        print(f"✅ All {len(loaded_data['embeddings'])} embeddings are valid 512-dimensional vectors")
        
    except Exception as e:
        print(f"❌ Embeddings file validation failed: {e}")
        raise
    
    # Assertions
    assert len(embeddings_data) >= 8, f"Should have embeddings for at least 8 entities, got {len(embeddings_data)}"
    assert embeddings_file.exists(), "Embeddings file should be created"
    assert embeddings_file.stat().st_size > 1000, "Embeddings file should not be empty"


@pytest.mark.asyncio
async def test_ground_truth_matching_with_roster(recognition_service, mock_images_path, project_root):
    """
    Test ground truth matching using the generated embeddings file.
    
    This test loads the embeddings file and tests actual face matching
    against known ground truth images.
    """
    # Check if embeddings file exists
    embeddings_file = project_root / "roster" / "data" / "insightface_embeddings.json"
    if not embeddings_file.exists():
        pytest.skip("Embeddings file not found - run test_generate_embeddings_file_for_roster first")
    
    print(f"🔍 Testing ground truth matching with roster...")
    print(f"📁 Using embeddings from: {embeddings_file}")
    
    # Test a subset of ground truth images
    test_images = [
        ("liam-maloney-home.jpg", ["Liam Maloney"]),
        ("kirstie-boat.jpg", ["Kirstie McCarrel"]),
        ("bea-nye.jpg", ["Bea Burke"]),
        ("ccqw-bar.jpg", ["Caitlin Weaver"]),
        ("maria-cocktail.jpg", ["Maria Correonero"])
    ]
    
    total_tests = 0
    correct_matches = 0
    match_results = []
    
    for image_filename, expected_people in test_images:
        image_path = mock_images_path / image_filename
        
        if not image_path.exists():
            print(f"⚠️  Test image not found: {image_filename}")
            continue
        
        try:
            print(f"\n🎯 Testing: {image_filename}")
            print(f"   Expected: {expected_people}")
            
            # Load and process image
            image = Image.open(image_path)
            result = await recognition_service.recognize_faces(image)
            
            total_tests += 1
            
            # Check for matches
            detected_faces = len(result.face_detections)
            matches_found = len(result.matches)
            
            print(f"   Detected faces: {detected_faces}")
            print(f"   Matches found: {matches_found}")
            
            if matches_found > 0:
                # Check if any match is correct
                matched_names = [match.entry.name for match in result.matches]
                similarities = [match.similarity for match in result.matches]
                
                print(f"   Matched names: {matched_names}")
                print(f"   Similarities: {[f'{s:.3f}' for s in similarities]}")
                
                # Check if any expected person was matched
                correct_match = any(name in matched_names for name in expected_people)
                if correct_match:
                    correct_matches += 1
                    status = "✅ CORRECT"
                else:
                    status = "❌ WRONG MATCH"
            else:
                status = "❓ NO MATCHES"
            
            match_results.append({
                "image": image_filename,
                "expected": expected_people,
                "detected_faces": detected_faces,
                "matches": [{"name": m.entry.name, "similarity": m.similarity} for m in result.matches],
                "correct": matches_found > 0 and any(name in [m.entry.name for m in result.matches] for name in expected_people)
            })
            
            print(f"   Result: {status}")
            
        except Exception as e:
            print(f"💥 Error testing {image_filename}: {e}")
            continue
    
    # Calculate results
    if total_tests > 0:
        accuracy = correct_matches / total_tests
        
        print(f"\n=== Ground Truth Matching Results ===")
        print(f"Total tests: {total_tests}")
        print(f"Correct matches: {correct_matches}")
        print(f"Accuracy: {accuracy:.2%}")
        
        # Show detailed results
        for result in match_results:
            status = "✅" if result["correct"] else "❌"
            print(f"{status} {result['image']}: expected {result['expected']}, "
                  f"got {len(result['matches'])} matches")
            if result["matches"]:
                for match in result["matches"]:
                    print(f"    - {match['name']}: {match['similarity']:.3f}")
        
        # Assertions for meaningful testing
        assert total_tests >= 3, f"Should test at least 3 images, got {total_tests}"
        assert accuracy >= 0.60, f"Should have ≥60% accuracy, got {accuracy:.2%}"
        
    else:
        pytest.fail("No test images could be processed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

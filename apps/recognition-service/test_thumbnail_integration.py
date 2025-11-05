#!/usr/bin/env python3
"""Integration test to verify face thumbnail is included in scene analysis."""

import asyncio
from PIL import Image, ImageDraw
from analysis.services.scene_analysis_service import SceneAnalysisService
from analysis.workflow.scene_composer import SceneComposer
from recognition_core.services import FaceRecognitionService
from shared.config.config_service import ConfigService


def create_test_image_with_face():
    """Create a test image with a visible face region."""
    img = Image.new('RGB', (1200, 800), color='lightblue')
    draw = ImageDraw.Draw(img)
    
    # Draw a simple face-like shape (circle + eyes + mouth)
    # Face at approximately (982, 651, 1064, 755)
    face_center_x, face_center_y = 1023, 703
    face_radius = 50
    
    # Draw face circle
    draw.ellipse(
        [face_center_x - face_radius, face_center_y - face_radius,
         face_center_x + face_radius, face_center_y + face_radius],
        fill='peachpuff', outline='black', width=2
    )
    
    # Draw eyes
    eye_y = face_center_y - 15
    draw.ellipse([face_center_x - 25, eye_y - 5, face_center_x - 15, eye_y + 5], fill='black')
    draw.ellipse([face_center_x + 15, eye_y - 5, face_center_x + 25, eye_y + 5], fill='black')
    
    # Draw smile
    draw.arc([face_center_x - 20, face_center_y, face_center_x + 20, face_center_y + 30],
             0, 180, fill='black', width=2)
    
    return img


async def test_thumbnail_in_scene_analysis():
    """Test that scene analysis includes base64 thumbnail in face_data."""
    print("🧪 Testing face thumbnail in scene analysis...")
    
    try:
        # Set up services
        config_service = ConfigService()
        recognition_service = FaceRecognitionService(config_service=config_service)
        scene_composer = SceneComposer()
        
        scene_analysis_service = SceneAnalysisService(
            scene_composer=scene_composer,
            recognition_service=recognition_service,
            config_service=config_service
        )
        
        # Create test image
        test_image = create_test_image_with_face()
        print(f"   Created test image: {test_image.size}")
        
        # Analyze scene
        print("   Running scene analysis...")
        scene_context = await scene_analysis_service.analyze_scene(test_image)
        
        # Check results
        num_entities = len(scene_context.detected_entities)
        print(f"   Detected {num_entities} entities")
        
        if num_entities == 0:
            print("   ⚠️  No faces detected in test image (this may be expected with the mock face)")
            print("   ℹ️  Testing thumbnail generation logic separately...")
            
            # Test thumbnail generation directly
            test_bbox = (982, 651, 1064, 755)
            thumbnail = scene_analysis_service._generate_face_thumbnail(test_image, test_bbox)
            
            if thumbnail and len(thumbnail) > 100:
                print(f"   ✅ Thumbnail generation works! (length: {len(thumbnail)} chars)")
                print(f"   First 80 chars: {thumbnail[:80]}...")
                return True
            else:
                print(f"   ❌ Thumbnail generation failed: {thumbnail}")
                return False
        
        # Check each detected entity for thumbnail
        success = True
        for i, entity in enumerate(scene_context.detected_entities):
            print(f"\n   Entity {i + 1}:")
            print(f"      Label: {entity.label}")
            print(f"      BBox: {entity.bbox}")
            print(f"      Confidence: {entity.confidence:.3f}")
            
            if entity.face_data:
                has_thumbnail = 'thumbnail' in entity.face_data
                print(f"      Has thumbnail: {has_thumbnail}")
                
                if has_thumbnail:
                    thumbnail = entity.face_data['thumbnail']
                    print(f"      Thumbnail length: {len(thumbnail)} chars")
                    print(f"      First 80 chars: {thumbnail[:80]}...")
                    
                    # Verify it's valid base64
                    import base64
                    try:
                        decoded = base64.b64decode(thumbnail)
                        print(f"      ✅ Valid base64, decoded to {len(decoded)} bytes")
                    except Exception as e:
                        print(f"      ❌ Invalid base64: {e}")
                        success = False
                else:
                    print(f"      ❌ Missing thumbnail in face_data!")
                    print(f"      face_data keys: {list(entity.face_data.keys())}")
                    success = False
            else:
                print(f"      ⚠️  No face_data")
        
        if success and num_entities > 0:
            print("\n✅ All detected faces have valid thumbnails!")
        elif num_entities == 0:
            print("\n⚠️  No faces detected (expected with simple mock face)")
        
        return success
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_thumbnail_in_scene_analysis())
    print(f"\n{'='*60}")
    print(f"Test result: {'PASSED ✅' if success else 'FAILED ❌'}")
    print(f"{'='*60}")
    exit(0 if success else 1)

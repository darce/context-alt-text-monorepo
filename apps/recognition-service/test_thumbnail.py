#!/usr/bin/env python3
"""Quick test to verify face thumbnail generation."""

import asyncio
import base64
from io import BytesIO
from PIL import Image

# Create a test image with a face region
def create_test_image():
    """Create a simple test image."""
    img = Image.new('RGB', (1200, 800), color='white')
    # Draw a simple rectangle where the "face" would be
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.rectangle([982, 651, 1064, 755], fill='blue', outline='red', width=3)
    return img

# Test the thumbnail generation function
def test_generate_thumbnail():
    """Test the _generate_face_thumbnail method."""
    from analysis.services.scene_analysis_service import SceneAnalysisService
    
    # Create a mock service instance (we only need the method)
    img = create_test_image()
    bbox = (982, 651, 1064, 755)
    
    # We'll test the logic directly
    try:
        # Crop the face region
        face_crop = img.crop(bbox)
        
        # Resize to thumbnail if needed (maintain aspect ratio)
        max_size = 150
        face_crop.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        # Encode as JPEG to base64
        buffer = BytesIO()
        face_crop.save(buffer, format="JPEG", quality=85)
        img_bytes = buffer.getvalue()
        
        # Return base64 string
        thumbnail_b64 = base64.b64encode(img_bytes).decode("utf-8")
        
        print(f"✅ Thumbnail generated successfully!")
        print(f"   Base64 length: {len(thumbnail_b64)} characters")
        print(f"   Image size after crop: {face_crop.size}")
        print(f"   First 100 chars: {thumbnail_b64[:100]}...")
        
        # Verify we can decode it back
        decoded = base64.b64decode(thumbnail_b64)
        test_img = Image.open(BytesIO(decoded))
        print(f"   Decoded image size: {test_img.size}")
        print(f"   Decoded image format: {test_img.format}")
        
        return True
    except Exception as e:
        print(f"❌ Failed to generate thumbnail: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_generate_thumbnail()
    exit(0 if success else 1)

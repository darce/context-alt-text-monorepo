#!/usr/bin/env python3
"""Create micro dataset by symlinking from main datasets.

This script creates the micro dataset for testing by symlinking
all reference images and scenes for Kirstie McCarrel and Caitlin Weaver,
while keeping Bea Burke only as an entity reference.
"""

import os
import shutil
from pathlib import Path


def create_micro_dataset():
    """Create micro dataset with symlinks to main dataset."""
    
    # Base paths
    base_dir = Path("/Users/daniel/Development/__hugging-face/entity-identifier-api")
    micro_dir = base_dir / "datasets" / "micro"
    
    # Source paths
    entities_source = base_dir / "scripts" / "mock_entities"
    scenes_source = base_dir / "scripts" / "mock_images"
    
    # Target paths
    entities_target = micro_dir / "entities"
    scenes_target = micro_dir / "scenes"
    
    # Create target directories
    entities_target.mkdir(parents=True, exist_ok=True)
    scenes_target.mkdir(parents=True, exist_ok=True)
    
    # Clear existing symlinks
    for item in entities_target.iterdir():
        if item.is_symlink():
            item.unlink()
    
    for item in scenes_target.iterdir():
        if item.is_symlink():
            item.unlink()
    
    # Entity images to symlink - all reference images for core entities
    entity_files = [
        # All Caitlin Weaver reference images
        "entity-caitlin-weaver.jpg",
        "entity-caitlin-weaver-2.jpg", 
        "entity-caitlin-weaver-3.jpg",
        "entity-caitlin-weaver-4.jpg",
        "entity-caitlin-weaver-5.jpg",
        # All Kirstie McCarrel reference images  
        "entity-kirstie-mccarrel.jpg",
        # Keep Bea Burke as entity reference only
        "entity-bea-burke.jpg",
        # Maria Correonero reference images
        "entity-maria-correonero.jpg",
        "entity-maria-correonero-2.jpg",
        # Ryann Wiseman reference images
        "entity-ryann-wiseman.jpg",
        "entity-ryann-wiseman.png",
        # Erika Hansen Miller reference images
        "entity-erika-hansen-miller.jpg",
        "entity-erika-hansen-miller-2.jpg",
    ]
    
    # Scene images to symlink - all scenes for Kirstie McCarrel and Caitlin Weaver analysis
    scene_files = [
        # All Caitlin Weaver (CCQW) scenes
        "ccqw-antartica.jpg",
        "ccqw-bar.jpg", 
        "ccqw-erika.jpg",
        "ccqw-flowers.jpg",
        "ccqw-hair.jpg",
        "ccqw-occlusion-2.jpg",
        "ccqw-occlusion.jpg",
        "ccqw-purple.jpg",
        "ccqw-running-2.jpg",
        "ccqw-running.jpg",
        "ccqw-sunglasses-flowers.jpg",
        "ccqw-sunglasses.jpg",
        "ccqw-underexposed.jpg",
        "ccqw.blurry.jpg",
        # All Kirstie McCarrel scenes
        "kirstie-1.jpeg",
        "kirstie-boat_detected.jpg", 
        "kirstie-boat.jpg",
        "kirstie-daniel-sunglasses.jpg",
        "kirstie-pool.jpg",
        # Remove Bea Burke scenes for analysis
    ]
    
    # Create entity symlinks
    entities_created = 0
    for entity_file in entity_files:
        source_path = entities_source / entity_file
        target_path = entities_target / entity_file
        
        if source_path.exists():
            if target_path.exists():
                target_path.unlink()
            target_path.symlink_to(source_path)
            entities_created += 1
            print(f"Created entity symlink: {entity_file}")
        else:
            print(f"Warning: Entity file not found: {entity_file}")
    
    # Create scene symlinks
    scenes_created = 0
    for scene_file in scene_files:
        source_path = scenes_source / scene_file
        target_path = scenes_target / scene_file
        
        if source_path.exists():
            if target_path.exists():
                target_path.unlink()
            target_path.symlink_to(source_path)
            scenes_created += 1
            print(f"Created scene symlink: {scene_file}")
        else:
            print(f"Warning: Scene file not found: {scene_file}")
    
    print(f"\nMicro dataset created:")
    print(f"  Entities: {entities_created} files")
    print(f"  Scenes: {scenes_created} files")
    
    # Calculate total size
    total_size = 0
    for item in entities_target.iterdir():
        if item.is_file():
            total_size += item.stat().st_size
    
    for item in scenes_target.iterdir():
        if item.is_file():
            total_size += item.stat().st_size
    
    print(f"  Total size: {total_size / (1024*1024):.2f} MB")
    print("✓ Micro dataset created successfully")


if __name__ == "__main__":
    create_micro_dataset()

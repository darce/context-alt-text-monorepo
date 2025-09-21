"""
Embeddings format converter utility.
Converts between different embeddings file formats for roster compatibility.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Any
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingsFormatConverter:
    """Converts between different embeddings file formats."""
    
    @staticmethod
    def convert_augmented_to_roster_format(augmented_file_path: str, output_file_path: str = None) -> str:
        """
        Convert an augmented embeddings file to standard roster format.
        
        Args:
            augmented_file_path: Path to the augmented embeddings file
            output_file_path: Optional output path. If None, creates a _roster.json version
            
        Returns:
            Path to the converted roster file
        """
        try:
            # Load augmented embeddings
            with open(augmented_file_path, 'r') as f:
                data = json.load(f)
            
            if output_file_path is None:
                # Create output filename
                input_path = Path(augmented_file_path)
                output_file_path = str(input_path.parent / f"{input_path.stem}_roster.json")
            
            # Convert entries from dict format to list format
            roster_entries = []
            entries_dict = data.get('entries', {})
            
            for entity_name, entity_data in entries_dict.items():
                # Extract embedding
                embedding = entity_data.get('augmented_embedding')
                if not embedding:
                    logger.warning(f"No augmented_embedding found for {entity_name}, skipping")
                    continue
                
                # Create roster entry in standard format
                roster_entry = {
                    "name": entity_name,
                    "display_name": entity_name,
                    "metadata": entity_data.get('metadata', {}),
                    "aggregate_embedding": embedding,
                    "image_count": entity_data.get('metadata', {}).get('total_images', 1),
                    "reference_images": [
                        {
                            "image_path": None,  # Not stored in augmented format
                            "embedding": embedding,
                            "metadata": {
                                "source": "augmented_embeddings",
                                "original_source_paths": entity_data.get('metadata', {}).get('source_paths', [])
                            }
                        }
                    ]
                }
                
                roster_entries.append(roster_entry)
            
            # Create roster format
            roster_data = {
                "version": "1.0",
                "entry_count": len(roster_entries),
                "entries": roster_entries,
                "metadata": {
                    "converted_from": augmented_file_path,
                    "original_format": "augmented_embeddings",
                    "model_name": data.get('model_name'),
                    "embedding_dimension": data.get('embedding_dimension'),
                    "created_timestamp": data.get('created_timestamp')
                }
            }
            
            # Save converted file
            with open(output_file_path, 'w') as f:
                json.dump(roster_data, f, indent=2)
            
            logger.info(f"✅ Converted {len(roster_entries)} entries from {augmented_file_path} to {output_file_path}")
            return output_file_path
            
        except Exception as e:
            logger.error(f"❌ Failed to convert embeddings format: {e}")
            raise
    
    @staticmethod
    def verify_roster_format(file_path: str) -> bool:
        """
        Verify if a file is in the expected roster format.
        
        Args:
            file_path: Path to the file to verify
            
        Returns:
            True if the file is in roster format, False otherwise
        """
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            # Check for roster format characteristics
            if not isinstance(data.get('entries'), list):
                return False
            
            if len(data.get('entries', [])) > 0:
                first_entry = data['entries'][0]
                required_fields = ['name', 'reference_images']
                if not all(field in first_entry for field in required_fields):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error verifying roster format: {e}")
            return False
    
    @staticmethod
    def is_augmented_format(file_path: str) -> bool:
        """
        Check if a file is in augmented embeddings format.
        
        Args:
            file_path: Path to the file to check
            
        Returns:
            True if the file is in augmented format, False otherwise
        """
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            # Check for augmented format characteristics
            entries = data.get('entries', {})
            if not isinstance(entries, dict):
                return False
            
            # Check if entries contain augmented_embedding
            for entity_name, entity_data in entries.items():
                if 'augmented_embedding' in entity_data:
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking augmented format: {e}")
            return False


def convert_embeddings_if_needed(file_path: str) -> str:
    """
    Convert embeddings file to roster format if needed.
    
    Args:
        file_path: Path to the embeddings file
        
    Returns:
        Path to the roster-compatible file
    """
    converter = EmbeddingsFormatConverter()
    
    # Check if already in roster format
    if converter.verify_roster_format(file_path):
        logger.info(f"File {file_path} is already in roster format")
        return file_path
    
    # Check if it's augmented format that needs conversion
    if converter.is_augmented_format(file_path):
        logger.info(f"Converting augmented embeddings file {file_path} to roster format")
        return converter.convert_augmented_to_roster_format(file_path)
    
    # Unknown format
    logger.warning(f"Unknown embeddings format in {file_path}, attempting to use as-is")
    return file_path

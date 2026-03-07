{
  "goals": [
    "Generate a lightweight derived image before vision inference to reduce inference cost and latency while preserving the original photo"
  ],

  "database": {
    "engine": "SQLite",
    "tables": {
      "photos": {
        "columns": {
          "id": "INTEGER PRIMARY KEY",
          "file_path": "TEXT NOT NULL UNIQUE",
          "file_name": "TEXT NOT NULL",
          "folder": "TEXT NOT NULL",
          "sha256": "TEXT NULL",
          "created_at_fs": "TEXT NULL",
          "discovered_at": "TEXT NOT NULL",
          "processed": "INTEGER NOT NULL DEFAULT 0",
          "processed_at": "TEXT NULL",
          "moved_to_path": "TEXT NULL",
          "vision_status": "TEXT NOT NULL DEFAULT 'pending'",
          "vision_description": "TEXT NULL",
          "vision_model": "TEXT NULL",
          "significance_score": "REAL NULL",
          "is_remote_candidate": "INTEGER NOT NULL DEFAULT 0",
          "remote_uploaded": "INTEGER NOT NULL DEFAULT 0",
          "remote_uploaded_at": "TEXT NULL",
          "remote_url": "TEXT NULL",
          "original_width": "INTEGER NULL",
          "original_height": "INTEGER NULL",
          "vision_preview_path": "TEXT NULL",
          "vision_input_width": "INTEGER NULL",
          "vision_input_height": "INTEGER NULL",
          "error_message": "TEXT NULL"
        }
      }
    }
  },

  "file_processing": {
    "photo_inbox_dir": "./data/photos/inbox",
    "photo_processed_dir": "./data/photos/processed",
    "vision_preview_dir": "./data/photos/vision_preview",
    "supported_extensions": [
      ".jpg",
      ".jpeg",
      ".png",
      ".webp"
    ],
    "preprocessing_rules": [
      "Never modify the original image before analysis",
      "Generate a derived image for vision inference",
      "Correct EXIF orientation before resizing if metadata is available",
      "Resize the derived image so the longest side is between 1280 and 1600 pixels",
      "Use JPEG for the derived vision image unless transparency is required",
      "Store both original and derived dimensions in the database"
    ],
    "processing_rules": [
      "New files are indexed in the DB first",
      "Each new file gets a process_photo task",
      "Vision runs on the derived preview image, not the original",
      "Vision output is stored in photos table",
      "Each processed image gets a significance score",
      "Only images selected by the agent should be remotely uploaded",
      "On success the file is moved to processed folder",
      "On failure the file stays in place and error is stored"
    ]
  },

  "task_handlers": {
    "process_photo": {
      "steps": [
        "Load photo metadata",
        "Read original image dimensions",
        "Generate oriented and resized vision preview image",
        "Run local vision model on the preview image",
        "Persist description and model",
        "Score image significance",
        "Mark as remote candidate if score passes threshold",
        "Move original file to processed folder",
        "Mark photo processed"
      ]
    }
  },

  "models": {
    "PhotoRecord": {
      "id": "int",
      "file_path": "str",
      "processed": "bool",
      "vision_status": "str",
      "vision_description": "str | None",
      "significance_score": "float | None",
      "is_remote_candidate": "bool",
      "remote_uploaded": "bool",
      "remote_url": "str | None",
      "original_width": "int | None",
      "original_height": "int | None",
      "vision_preview_path": "str | None",
      "vision_input_width": "int | None",
      "vision_input_height": "int | None",
      "moved_to_path": "str | None"
    }
  },

  "config_schema": {
    "image_preprocessing": {
      "enabled": "bool = true",
      "tool": "str = pillow",
      "correct_exif_orientation": "bool = true",
      "resize_for_vision": "bool = true",
      "vision_max_dimension": "int = 1600",
      "vision_min_dimension": "int = 1280",
      "vision_preview_format": "str = jpeg",
      "vision_preview_quality": "int = 85"
    }
  },

  "config_example": {
    "image_preprocessing": {
      "enabled": true,
      "tool": "pillow",
      "correct_exif_orientation": true,
      "resize_for_vision": true,
      "vision_max_dimension": 1600,
      "vision_min_dimension": 1280,
      "vision_preview_format": "jpeg",
      "vision_preview_quality": 85
    }
  },

  "file_structure": {
    "src/agent/services/image_preprocessing_service.py": "Creates derived preview images for vision inference using Pillow",
    "tests/test_image_preprocessing.py": "Tests EXIF orientation correction and resizing pipeline"
  }
}
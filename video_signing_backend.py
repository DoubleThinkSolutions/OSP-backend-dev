#!/usr/bin/env python3
"""
Video Signing Backend Service
Integrates with Axis Signed Video Framework to sign video content from mobile devices
"""

import os
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

# Web framework imports (using FastAPI as example)
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
import uvicorn

# Database imports (using SQLAlchemy as example)
from sqlalchemy import create_engine, Column, Integer, String, DateTime, LargeBinary, Boolean
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
@dataclass
class SigningConfig:
    # Path to the signed video framework library
    signed_video_lib_path: str = os.getenv("SIGNED_VIDEO_LIB_PATH", "/usr/local/lib/libsigned-video-framework.so")
    
    # Path to signing executable (from examples)
    signer_executable: str = os.getenv("SIGNER_EXECUTABLE", "/usr/local/bin/signer")
    
    # Private key for signing (in production, use secure key management)
    private_key_path: str = os.getenv("PRIVATE_KEY_PATH", "/etc/video-signing/private.pem")
    
    # Private key password (for development - use secure key management in production)
    private_key_password: str = os.getenv("PRIVATE_KEY_PASSWORD", "")
    
    # Temporary directory for processing
    temp_dir: str = os.getenv("TEMP_DIR", "/tmp/video-signing")
    
    # Supported video formats
    supported_formats: list = None
    
    def __post_init__(self):
        if self.supported_formats is None:
            self.supported_formats = ['.mp4', '.mov', '.avi', '.mkv', '.m4v']

config = SigningConfig()

# Database setup
DATABASE_URL = "sqlite:///./signed_videos.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class SignedVideo(Base):
    __tablename__ = "signed_videos"
    
    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String, index=True)
    file_hash = Column(String, index=True)
    signed_filename = Column(String)
    upload_timestamp = Column(DateTime, default=datetime.utcnow)
    signing_timestamp = Column(DateTime)
    device_info = Column(String)  # JSON string with device metadata
    is_signed = Column(Boolean, default=False)
    signing_status = Column(String, default="pending")
    error_message = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)

# FastAPI app
app = FastAPI(title="Video Signing Service", version="1.0.0")

class VideoSigningService:
    """Service class to handle video signing operations"""
    
    def __init__(self, config: SigningConfig):
        self.config = config
        self.ensure_directories()
        self.validate_dependencies()
    
    def ensure_directories(self):
        """Ensure required directories exist"""
        os.makedirs(self.config.temp_dir, exist_ok=True)
        
    def validate_dependencies(self):
        """Validate that required dependencies are available"""
        missing_deps = []
        
        if not os.path.exists(self.config.signed_video_lib_path):
            missing_deps.append(f"Signed video library: {self.config.signed_video_lib_path}")
            
        if not os.path.exists(self.config.signer_executable):
            missing_deps.append(f"Signer executable: {self.config.signer_executable}")
            
        if not os.path.exists(self.config.private_key_path):
            missing_deps.append(f"Private key: {self.config.private_key_path}")
        
        if missing_deps:
            logger.error("Missing dependencies:")
            for dep in missing_deps:
                logger.error(f"  - {dep}")
            logger.error("Please ensure Axis Signed Video Framework is properly installed")
        else:
            logger.info("All dependencies found successfully")
            
        # Test signer executable
        try:
            result = subprocess.run([self.config.signer_executable, "--help"], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                logger.info("Signer executable is working correctly")
            else:
                logger.warning(f"Signer executable returned code {result.returncode}")
        except Exception as e:
            logger.error(f"Failed to test signer executable: {e}")
    
    def calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file"""
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
    
    def is_supported_format(self, filename: str) -> bool:
        """Check if file format is supported"""
        return Path(filename).suffix.lower() in self.config.supported_formats
    
    def sign_video(self, input_path: str, output_path: str) -> Dict[str, Any]:
        """
        Sign video using Axis Signed Video Framework
        
        Args:
            input_path: Path to input video file
            output_path: Path where signed video will be saved
            
        Returns:
            Dictionary with signing results
        """
        try:
            # Prepare signing command
            # This assumes the signer executable from the examples repository
            cmd = [
                self.config.signer_executable,
                "--input", input_path,
                "--output", output_path,
                "--key", self.config.private_key_path
            ]
            
            # Add password if provided
            if self.config.private_key_password:
                cmd.extend(["--key-password", self.config.private_key_password])
            
            # Add verbose flag for debugging
            cmd.append("--verbose")
            
            logger.info(f"Executing signing command: {' '.join(cmd[:-2])}... [password hidden]")
            
            # Set environment variables for GStreamer
            env = os.environ.copy()
            env['GST_PLUGIN_PATH'] = '/usr/lib/x86_64-linux-gnu/gstreamer-1.0:/usr/local/lib/gstreamer-1.0'
            
            # Execute signing process
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                env=env
            )
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "output_path": output_path,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
            else:
                return {
                    "success": False,
                    "error": f"Signing failed with code {result.returncode}",
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
                
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Signing process timed out"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Signing process failed: {str(e)}"
            }
    
    def process_video_file(self, file_path: str, original_filename: str, device_info: Dict = None) -> Dict[str, Any]:
        """
        Complete video processing pipeline
        
        Args:
            file_path: Path to uploaded video file
            original_filename: Original filename from mobile device
            device_info: Device metadata from mobile app
            
        Returns:
            Processing results
        """
        try:
            # Calculate file hash for integrity verification
            file_hash = self.calculate_file_hash(file_path)
            
            # Generate output filename
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            base_name = Path(original_filename).stem
            output_filename = f"{base_name}_signed_{timestamp}.mp4"
            output_path = os.path.join(self.config.temp_dir, output_filename)
            
            # Sign the video
            signing_result = self.sign_video(file_path, output_path)
            
            if signing_result["success"]:
                return {
                    "success": True,
                    "signed_file_path": output_path,
                    "signed_filename": output_filename,
                    "file_hash": file_hash,
                    "signing_details": signing_result
                }
            else:
                return {
                    "success": False,
                    "error": signing_result["error"],
                    "file_hash": file_hash
                }
                
        except Exception as e:
            logger.error(f"Video processing failed: {str(e)}")
            return {
                "success": False,
                "error": f"Processing failed: {str(e)}"
            }

# Initialize service
signing_service = VideoSigningService(config)

def get_db():
    """Database dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/upload-video/")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    device_info: str = None
):
    """
    Upload and sign video from mobile device
    
    Args:
        file: Video file from mobile device
        device_info: JSON string with device metadata (OS, model, app version, etc.)
    """
    
    # Validate file format
    if not signing_service.is_supported_format(file.filename):
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file format. Supported: {config.supported_formats}"
        )
    
    # Save uploaded file temporarily
    temp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as temp_file:
            temp_file_path = temp_file.name
            content = await file.read()
            temp_file.write(content)
        
        # Create database record
        db = next(get_db())
        
        parsed_device_info = None
        if device_info:
            try:
                parsed_device_info = json.loads(device_info)
            except json.JSONDecodeError:
                logger.warning("Invalid device_info JSON provided")
        
        # Calculate file hash for database
        file_hash = signing_service.calculate_file_hash(temp_file_path)
        
        db_video = SignedVideo(
            original_filename=file.filename,
            file_hash=file_hash,
            device_info=device_info,
            signing_status="processing"
        )
        db.add(db_video)
        db.commit()
        db.refresh(db_video)
        
        # Process video in background
        background_tasks.add_task(
            process_video_background,
            db_video.id,
            temp_file_path,
            file.filename,
            parsed_device_info
        )
        
        return {
            "message": "Video uploaded successfully",
            "video_id": db_video.id,
            "status": "processing",
            "file_hash": file_hash
        }
        
    except Exception as e:
        # Clean up temp file on error
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        
        logger.error(f"Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

async def process_video_background(video_id: int, temp_file_path: str, original_filename: str, device_info: Dict = None):
    """Background task to process and sign video"""
    db = SessionLocal()
    
    try:
        # Get database record
        db_video = db.query(SignedVideo).filter(SignedVideo.id == video_id).first()
        if not db_video:
            logger.error(f"Video record {video_id} not found")
            return
        
        # Process the video
        result = signing_service.process_video_file(temp_file_path, original_filename, device_info)
        
        if result["success"]:
            # Update database record
            db_video.signed_filename = result["signed_filename"]
            db_video.signing_timestamp = datetime.utcnow()
            db_video.is_signed = True
            db_video.signing_status = "completed"
            
            logger.info(f"Successfully signed video {video_id}: {result['signed_filename']}")
        else:
            # Update with error
            db_video.signing_status = "failed"
            db_video.error_message = result["error"]
            
            logger.error(f"Failed to sign video {video_id}: {result['error']}")
        
        db.commit()
        
    except Exception as e:
        logger.error(f"Background processing failed for video {video_id}: {str(e)}")
        
        # Update database with error
        db_video = db.query(SignedVideo).filter(SignedVideo.id == video_id).first()
        if db_video:
            db_video.signing_status = "failed"
            db_video.error_message = str(e)
            db.commit()
    
    finally:
        # Clean up temporary file
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        db.close()

@app.get("/video-status/{video_id}")
async def get_video_status(video_id: int):
    """Get signing status of uploaded video"""
    db = next(get_db())
    
    db_video = db.query(SignedVideo).filter(SignedVideo.id == video_id).first()
    if not db_video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    return {
        "video_id": video_id,
        "original_filename": db_video.original_filename,
        "file_hash": db_video.file_hash,
        "upload_timestamp": db_video.upload_timestamp,
        "signing_timestamp": db_video.signing_timestamp,
        "status": db_video.signing_status,
        "is_signed": db_video.is_signed,
        "error_message": db_video.error_message,
        "signed_filename": db_video.signed_filename
    }

@app.get("/download-signed-video/{video_id}")
async def download_signed_video(video_id: int):
    """Download signed video file"""
    db = next(get_db())
    
    db_video = db.query(SignedVideo).filter(SignedVideo.id == video_id).first()
    if not db_video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    if not db_video.is_signed:
        raise HTTPException(status_code=400, detail="Video not yet signed")
    
    signed_file_path = os.path.join(config.temp_dir, db_video.signed_filename)
    if not os.path.exists(signed_file_path):
        raise HTTPException(status_code=404, detail="Signed video file not found")
    
    return FileResponse(
        signed_file_path,
        media_type="video/mp4",
        filename=db_video.signed_filename
    )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow(),
        "dependencies": {
            "signed_video_lib": os.path.exists(config.signed_video_lib_path),
            "signer_executable": os.path.exists(config.signer_executable),
            "private_key": os.path.exists(config.private_key_path)
        }
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

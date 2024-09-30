from app.lib.Env import open_ai_api_key
from fastapi import APIRouter, File, UploadFile, HTTPException
import whisper
import os
import uuid
from pydub import AudioSegment
import shutil
import warnings
from pydantic import BaseModel
from openai import OpenAI
from app.lib.JsonSchemas import TranscriptionResponse

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))

client = OpenAI(api_key=open_ai_api_key)

# Ignore torch warning 
warnings.filterwarnings("ignore", category=FutureWarning)

api_router = APIRouter()

# Load Whisper model once at startup
model = whisper.load_model("tiny.en")  # Choose appropriate model size

# Function to clear the temp directory
def clear_temp_directory():
    temp_dir = 'temp'
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)

# Function to compress audio until it is under 24 MB
def compress_audio_until_target_size(audio: AudioSegment, target_size_mb=24, max_iterations=10):
    compressed_audio_path = f"temp/compressed_{uuid.uuid4()}.wav"
    
    # Start with default compression settings
    target_bitrate = "64k"
    target_sample_rate = 16000

    # Reduce file size iteratively
    for _ in range(max_iterations):
        # Export the audio with current compression settings
        audio.export(compressed_audio_path, format="wav", bitrate=target_bitrate, parameters=["-ar", str(target_sample_rate)])

        # Check the file size
        file_size_mb = os.path.getsize(compressed_audio_path) / (1024 * 1024)  # Size in MB
        if file_size_mb <= target_size_mb:
            break

        # If the file is too large, reduce the bitrate and sample rate
        target_bitrate = f"{int(target_bitrate[:-1]) // 2}k"  # Reduce bitrate by half
        target_sample_rate = max(8000, target_sample_rate // 2)  # Halve the sample rate but not below 8kHz

    return compressed_audio_path, file_size_mb

@api_router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(file: UploadFile = File(...)):
    clear_temp_directory()

    if not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an audio file.")

    try:
        # Save the uploaded file to the temp directory
        file_extension = os.path.splitext(file.filename)[1]
        temp_filename = f"{uuid.uuid4()}{file_extension}"
        temp_path = os.path.join("temp", temp_filename)

        with open(temp_path, "wb") as buffer:
            buffer.write(await file.read())

        # Load the audio file
        audio = AudioSegment.from_file(temp_path)

        # Compress audio until it is under 24 MB
        compressed_wav_path, compressed_size_mb = compress_audio_until_target_size(audio, target_size_mb=24)
        print(f"Compressed audio saved at: {compressed_wav_path} ({compressed_size_mb} MB)")

        # Transcribe the compressed audio file
        result = model.transcribe(compressed_wav_path, fp16=False)

        # Clean up temporary files
        os.remove(temp_path)
        os.remove(compressed_wav_path)

        transcription_file_path = os.path.join(BASE_DIR, 'transcription.txt')
        with open(transcription_file_path, 'w') as file_handle:
            file_handle.write(f"File Name: {file.filename}\n\n{result['text']}")
        # Return the transcription result
        return {"transcription": result["text"]}

    except Exception as e:
        clear_temp_directory()
        raise HTTPException(status_code=500, detail=str(e))
from app.lib.Env import open_ai_api_key
from fastapi import APIRouter, File, UploadFile, HTTPException
import os
import uuid
from pydub import AudioSegment
import shutil
import warnings
from openai import OpenAI
from app.lib.JsonSchemas import TranscriptionResponse
import asyncio

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))

client = OpenAI(api_key=open_ai_api_key)

# Ignore torch warning
warnings.filterwarnings("ignore", category=FutureWarning)

api_router = APIRouter()

# Function to clear the temp directory
def clear_temp_directory():
    temp_dir = 'temp'
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)
    print("Temp directory cleared.")

# Function to compress audio
def compress_audio_until_target_size(audio: AudioSegment, file_extension: str, target_size_bytes=26214400, max_iterations=10):
    print("Starting audio compression...")
    compressed_audio_path = f"temp/compressed_{uuid.uuid4()}.mp3"
    
    # Start with default compression settings
    target_bitrate = "64k"
    target_sample_rate = 16000

    # Iteratively reduce bitrate and sample rate until size fits
    for iteration in range(max_iterations):
        print(f"Iteration {iteration + 1}: Compressing with bitrate {target_bitrate} and sample rate {target_sample_rate}")
        audio.export(compressed_audio_path, format='mp3', bitrate=target_bitrate, parameters=["-ar", str(target_sample_rate)])
        file_size_bytes = os.path.getsize(compressed_audio_path)
        print(f"Compressed audio size: {file_size_bytes} bytes")

        if file_size_bytes <= target_size_bytes:
            print("Target size reached.")
            break
        
        target_bitrate_value = int(target_bitrate[:-1])
        if target_bitrate_value > 32:
            target_bitrate = f"{target_bitrate_value // 2}k"
        if target_sample_rate > 8000:
            target_sample_rate = max(8000, target_sample_rate // 2)

    return compressed_audio_path, file_size_bytes

# Function to transcribe a chunk (make this synchronous)
def transcribe_then_delete_chunk(chunk_path, idx):
    print(f"Transcribing chunk {idx} from {chunk_path}")
    with open(chunk_path, "rb") as chunk_file:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=chunk_file,
            response_format="text"
        )
        print(f"Chunk {idx} transcribed successfully.")
        os.remove(chunk_path)
        print(f"Chunk {idx} deleted after transcription.")
    return idx, result

# Main API route
@api_router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(file: UploadFile = File(...)):
    clear_temp_directory()

    if not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an audio file.")

    try:
        file_extension = os.path.splitext(file.filename)[1]
        temp_filename = f"{uuid.uuid4()}{file_extension}"
        temp_path = os.path.join("temp", temp_filename)

        # Stream file writing to avoid loading it fully in memory
        with open(temp_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):  # Read in 1MB chunks
                buffer.write(content)
        print(f"File {file.filename} saved to {temp_path}.")

        # Load and compress audio to its smallest size
        audio = AudioSegment.from_file(temp_path)
        compressed_audio_path, compressed_size_bytes = compress_audio_until_target_size(audio, file_extension)
        print(f"Compressed audio file path: {compressed_audio_path}, size: {compressed_size_bytes} bytes.")

        # Calculate the number of chunks based on the compressed size (26,214,400 bytes limit)
        max_chunk_size_bytes = 26214400  # 26,214,400 bytes
        num_chunks = int(compressed_size_bytes // max_chunk_size_bytes) + 1  # Calculate number of chunks
        print(f"Total number of chunks required: {num_chunks}.")

        # Split the audio into the required number of chunks
        compressed_audio = AudioSegment.from_file(compressed_audio_path)
        total_duration_ms = len(compressed_audio)
        chunk_duration_ms = total_duration_ms // num_chunks

        final_transcription = ""

        # Sequential processing of chunks
        for idx in range(num_chunks):
            start_time = idx * chunk_duration_ms
            end_time = (idx + 1) * chunk_duration_ms if idx < num_chunks - 1 else total_duration_ms
            chunk = compressed_audio[start_time:end_time]

            # Export chunk as MP3 with a low bitrate to ensure it stays under the limit
            chunk_path = f"temp/chunk_{idx}.mp3"
            chunk.export(chunk_path, format="mp3", bitrate="32k")  # Using a lower bitrate to shrink size
            chunk_size = os.path.getsize(chunk_path)
            print(f"Chunk {idx} saved to {chunk_path}, size: {chunk_size} bytes.")

            # Ensure chunk size is within limit before transcribing
            if chunk_size > max_chunk_size_bytes:
                print(f"Error: Chunk {idx} exceeds the size limit of {max_chunk_size_bytes} bytes.")
                raise HTTPException(status_code=413, detail=f"Chunk {idx} exceeds the size limit.")

            # Transcribe chunk
            idx, transcription = transcribe_then_delete_chunk(chunk_path, idx)
            final_transcription += transcription + " "  # Append transcription

        # Clean up compressed audio file
        os.remove(temp_path)
        os.remove(compressed_audio_path)
        print("Temporary files cleaned up.")

        # Save final transcription to a file
        transcription_file_path = os.path.join(BASE_DIR, 'transcription.txt')
        with open(transcription_file_path, 'w') as file_handle:
            file_handle.write(f"File Name: {file.filename}\n\n{final_transcription.strip()}")
        print(f"Transcription saved to {transcription_file_path}.")

        return {"transcription": final_transcription.strip()}

    except Exception as e:
        clear_temp_directory()
        print(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

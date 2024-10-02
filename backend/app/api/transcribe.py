from app.lib.Env import open_ai_api_key
from fastapi import APIRouter, File, UploadFile, HTTPException
import os
import uuid
from pydub import AudioSegment
from pydub.silence import split_on_silence
import shutil
import warnings
from openai import OpenAI
from app.lib.JsonSchemas import TranscriptionResponse
import asyncio
from concurrent.futures import ThreadPoolExecutor

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

# Function to compress audio
def compress_audio_until_target_size(audio: AudioSegment, file_extension: str, target_size_bytes=26214400, max_iterations=10):
    compressed_audio_path = f"temp/compressed_{uuid.uuid4()}.mp3"
    
    # Start with default compression settings
    target_bitrate = "64k"
    target_sample_rate = 16000

    # Iteratively reduce bitrate and sample rate until size fits
    for _ in range(max_iterations):
        audio.export(compressed_audio_path, format='mp3', bitrate=target_bitrate, parameters=["-ar", str(target_sample_rate)])
        file_size_bytes = os.path.getsize(compressed_audio_path)
        
        if file_size_bytes <= target_size_bytes:
            break
        
        target_bitrate_value = int(target_bitrate[:-1])
        if target_bitrate_value > 32:
            target_bitrate = f"{target_bitrate_value // 2}k"
        if target_sample_rate > 8000:
            target_sample_rate = max(8000, target_sample_rate // 2)

    return compressed_audio_path, file_size_bytes

# Function to transcribe a chunk (make this synchronous)
def transcribe_chunk(chunk_path, idx):
    with open(chunk_path, "rb") as chunk_file:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=chunk_file,
            response_format="text"
        )
    return idx, result

# Function to selectively split a large chunk on sentence breaks if it exceeds size
def split_if_exceeds_size(chunk: AudioSegment, target_size_bytes=26214400, silence_thresh=-40, min_silence_len=500):
    # Check if chunk exceeds size limit
    if len(chunk.raw_data) > target_size_bytes:
        # Split on silence (sentence breaks)
        return split_on_silence(chunk, min_silence_len=min_silence_len, silence_thresh=silence_thresh)
    else:
        # If it's within size, return the chunk as is
        return [chunk]

# Function to split audio into a few large chunks first, then split on sentence breaks only if needed
def split_audio_into_large_chunks(audio: AudioSegment, target_num_chunks: int, target_size_bytes=26214400, silence_thresh=-40, min_silence_len=500):
    total_duration_ms = len(audio)
    chunk_duration_ms = total_duration_ms // target_num_chunks
    
    large_chunks = []
    for i in range(target_num_chunks):
        start_time = i * chunk_duration_ms
        end_time = (i + 1) * chunk_duration_ms
        chunk = audio[start_time:end_time]
        
        # Split the chunk only if it exceeds size
        split_chunks = split_if_exceeds_size(chunk, target_size_bytes, silence_thresh, min_silence_len)
        large_chunks.extend(split_chunks)
    
    return large_chunks

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

        with open(temp_path, "wb") as buffer:
            buffer.write(await file.read())

        # Load and compress audio
        audio = AudioSegment.from_file(temp_path)
        compressed_audio_path, compressed_size_bytes = compress_audio_until_target_size(audio, file_extension)
        compressed_audio = AudioSegment.from_file(compressed_audio_path)

        # Split the compressed audio into a few large chunks first
        audio_chunks = split_audio_into_large_chunks(compressed_audio, target_num_chunks=5)

        # Save each chunk to a file and transcribe in parallel
        transcriptions = [""] * len(audio_chunks)
        with ThreadPoolExecutor() as executor:
            loop = asyncio.get_running_loop()
            tasks = []
            for idx, chunk in enumerate(audio_chunks):
                chunk_path = f"temp/chunk_{idx}.wav"
                chunk.export(chunk_path, format="wav")  # Save each chunk to a file
                tasks.append(loop.run_in_executor(executor, transcribe_chunk, chunk_path, idx))
            
            # Ensure the transcriptions are ordered by chunk index
            results = await asyncio.gather(*tasks)
            for idx, transcription in results:
                transcriptions[idx] = transcription  # Store transcription in the correct order

        final_transcription = " ".join(transcriptions)

        # Clean up
        os.remove(temp_path)
        os.remove(compressed_audio_path)

        transcription_file_path = os.path.join(BASE_DIR, 'transcription.txt')
        with open(transcription_file_path, 'w') as file_handle:
            file_handle.write(f"File Name: {file.filename}\n\n{final_transcription}")

        return {"transcription": final_transcription}

    except Exception as e:
        clear_temp_directory()
        raise HTTPException(status_code=500, detail=str(e))
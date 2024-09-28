from fastapi import APIRouter, File, UploadFile, HTTPException
import whisper
import os
import uuid
from pydub import AudioSegment
import shutil
import math
import warnings
from pydantic import BaseModel

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

# Function to compress audio
def compress_audio(audio: AudioSegment, target_bitrate="64k", target_sample_rate=16000):
    # Reduce channels to mono, downsample to target sample rate, and adjust bitrate
    audio = audio.set_frame_rate(target_sample_rate)
    audio = audio.set_channels(1)  # Mono
    compressed_audio_path = f"temp/compressed_{uuid.uuid4()}.wav"
    
    # Export compressed audio
    audio.export(compressed_audio_path, format="wav", bitrate=target_bitrate)
    return compressed_audio_path

class TranscriptionResponse(BaseModel):
    transcription: str

@api_router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(file: UploadFile = File(...)):
    print(f"Received file: {file.filename}")
    # Clear temp directory at the start of the request
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

        # Convert and compress the audio file to reduce size
        audio = AudioSegment.from_file(temp_path)
        compressed_wav_path = compress_audio(audio)
        print(f"Compressed audio saved at: {compressed_wav_path}")

        # Calculate the file size of the compressed audio
        wav_file_size = os.path.getsize(compressed_wav_path) / (1024 * 1024)  # Size in MB
        print(f"Compressed WAV file size: {wav_file_size} MB")

        # Calculate chunk duration based on file size and desired chunk size (24 MB)
        total_duration_ms = len(audio)  # Total duration in milliseconds
        chunk_size_mb = 24  # Target chunk size in MB
        chunk_duration_ms = total_duration_ms * (chunk_size_mb / wav_file_size)  # Calculate chunk duration in ms
        print(f"Chunk duration: {chunk_duration_ms / 1000 / 60} minutes")

        # Split audio based on duration
        num_chunks = math.ceil(total_duration_ms / chunk_duration_ms)
        print(f"Num chunks: {num_chunks}")

        transcriptions = []
        for i in range(num_chunks):
            start_time = i * chunk_duration_ms  # Start time in ms
            end_time = min((i + 1) * chunk_duration_ms, total_duration_ms)  # End time in ms
            print(f"Processing chunk {i + 1} from {start_time} ms to {end_time} ms")

            chunk = audio[start_time:end_time]

            # Export chunk
            chunk_wav_path = os.path.splitext(compressed_wav_path)[0] + f"_chunk_{i}.wav"
            chunk.export(chunk_wav_path, format="wav")

            # Transcribe chunk
            print(f"Transcribing chunk {i + 1}")
            result = model.transcribe(chunk_wav_path, fp16=False)
            transcriptions.append(result["text"])

            # Clean up chunk file
            os.remove(chunk_wav_path)
            print(f"Completed chunk {i + 1}")

        # Clean up temporary files
        os.remove(temp_path)
        os.remove(compressed_wav_path)

        # Combine all transcriptions
        combined_transcription = " ".join(transcriptions)
        print(f"Combined transcription: {combined_transcription}")

        return {"transcription": combined_transcription}

    except Exception as e:
        clear_temp_directory()  # Ensure temp is cleared on error
        raise HTTPException(status_code=500, detail=str(e))

from app.lib.Env import open_ai_api_key
from fastapi import APIRouter, File, UploadFile, HTTPException
# import whisper
import os
import uuid
from pydub import AudioSegment
import shutil
import warnings
# from pydantic import BaseModel
from openai import OpenAI
from app.lib.JsonSchemas import TranscriptionResponse

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))

client = OpenAI(api_key=open_ai_api_key)

# Ignore torch warning 
warnings.filterwarnings("ignore", category=FutureWarning)

api_router = APIRouter()

# Load Whisper model once at startup
# model = whisper.load_model("tiny.en")  # Choose appropriate model size

# Function to clear the temp directory
def clear_temp_directory():
    temp_dir = 'temp'
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)

def compress_audio_until_target_size(audio: AudioSegment, file_extension: str, target_size_bytes=26214400, max_iterations=10):
    compressed_audio_path = f"temp/compressed_{uuid.uuid4()}{file_extension}"  # Retain the original file extension
    
    # Start with default compression settings
    target_bitrate = "64k"  # Start with 64 kbps bitrate
    target_sample_rate = 16000  # Start with a 16kHz sample rate

    # Reduce file size iteratively
    for _ in range(max_iterations):
        # Export the audio in the same format as the original, adjusting bitrate and sample rate
        audio.export(compressed_audio_path, format=file_extension[1:], bitrate=target_bitrate, parameters=["-ar", str(target_sample_rate)])

        # Check the file size
        file_size_bytes = os.path.getsize(compressed_audio_path)
        print(f"Compressed file size: {file_size_bytes} bytes at {target_bitrate} and {target_sample_rate}Hz")

        # If the file size is within the target size, stop compressing
        if file_size_bytes <= target_size_bytes:
            break

        # Reduce the bitrate and sample rate gradually if file is too large
        target_bitrate_value = int(target_bitrate[:-1])
        if target_bitrate_value > 32:
            target_bitrate = f"{target_bitrate_value // 2}k"  # Reduce bitrate by half
        if target_sample_rate > 8000:
            target_sample_rate = max(8000, target_sample_rate // 2)  # Halve the sample rate but not below 8kHz

    # If the final file size is still larger than the target, raise an error
    if file_size_bytes > target_size_bytes:
        raise Exception(f"Unable to compress audio to target size. Final size: {file_size_bytes} bytes")

    return compressed_audio_path, file_size_bytes



def split_audio_to_fit_size(audio: AudioSegment, target_size_bytes=26214400):
    total_file_size_bytes = len(audio.raw_data)  # Get the total file size in bytes
    num_chunks = (total_file_size_bytes // target_size_bytes) + 1  # Calculate the number of chunks required
    
    # Calculate the duration of each chunk based on the number of chunks
    chunk_duration_ms = len(audio) // num_chunks  # Length of each chunk in milliseconds
    
    chunks = []
    for i in range(num_chunks):
        start_time = i * chunk_duration_ms
        end_time = (i + 1) * chunk_duration_ms
        chunk = audio[start_time:end_time]
        chunks.append(chunk)

    return chunks


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

        # Save the original file without encoding
        with open(temp_path, "wb") as buffer:
            buffer.write(await file.read())

        # Load the audio file
        audio = AudioSegment.from_file(temp_path)

        # Compress audio first
        compressed_wav_path, compressed_size_bytes = compress_audio_until_target_size(audio, file_extension, target_size_bytes=26214400)  # 25MB limit in bytes
        print(f"Compressed audio size: {compressed_size_bytes} bytes")

        max_file_size_bytes = 26214400  # 25MB in bytes

        # If the compressed file is larger than the allowed size, split it into chunks
        if compressed_size_bytes > max_file_size_bytes:
            # Reload the compressed audio file to split it
            compressed_audio = AudioSegment.from_file(compressed_wav_path)
            audio_chunks = split_audio_to_fit_size(compressed_audio, target_size_bytes=max_file_size_bytes)
            transcriptions = []
            for idx, chunk in enumerate(audio_chunks):
                chunk_path = f"temp/chunk_{idx}_{uuid.uuid4()}.wav"
                chunk.export(chunk_path, format="wav")  # Export each chunk in WAV format

                # Transcribe each chunk
                with open(chunk_path, "rb") as chunk_file:
                    result = client.audio.transcriptions.create(
                        model="whisper-1", 
                        file=chunk_file, 
                        response_format="text"
                    )
                    transcriptions.append(result)

            # Combine the transcriptions of each chunk
            final_transcription = " ".join(transcriptions)
        else:
            # If the compressed file is under the limit, transcribe it directly
            with open(compressed_wav_path, "rb") as compressed_audio_file:
                result = client.audio.transcriptions.create(
                    model="whisper-1", 
                    file=compressed_audio_file, 
                    response_format="text"
                )
            final_transcription = result

        # Clean up temporary files
        os.remove(temp_path)
        os.remove(compressed_wav_path)

        transcription_file_path = os.path.join(BASE_DIR, 'transcription.txt')
        with open(transcription_file_path, 'w') as file_handle:
            file_handle.write(f"File Name: {file.filename}\n\n{final_transcription}")

        return {"transcription": final_transcription}

    except Exception as e:
        clear_temp_directory()
        raise HTTPException(status_code=500, detail=str(e))

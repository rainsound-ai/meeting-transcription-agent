from app.lib.Env import open_ai_api_key
from fastapi import APIRouter, File, UploadFile, HTTPException
import whisper
import os
import uuid
from pydub import AudioSegment
import shutil
import math
import warnings
from pydantic import BaseModel
from openai import OpenAI

client = OpenAI(api_key=open_ai_api_key)

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


# Set your OpenAI API key

# Define the input model for transcription
class TranscriptionRequest(BaseModel):
    transcription: str

# Define the expected response model (if needed)
class SummaryResponse(BaseModel):
    transcription: str
    summary: str

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))

def chunk_text(text, max_tokens=2000):
    words = text.split()
    chunks = []
    current_chunk = []

    current_tokens = 0
    for word in words:
        # Estimate that each word is 1.33 tokens (rough approximation)
        token_estimate = len(word) / 4
        if current_tokens + token_estimate > max_tokens:
            chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_tokens = token_estimate
        else:
            current_chunk.append(word)
            current_tokens += token_estimate

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks

@api_router.post("/summarize")
async def summarize_transcription(request: TranscriptionRequest):
    try:
        print("Received request for summarization.")
        transcription = request.transcription.strip()

        # If transcription is empty, load from summary.txt
        if not transcription:
            print("No transcription provided. Attempting to read from summary.txt.")
            summary_file_path = os.path.join(BASE_DIR, 'summary.txt')

            if os.path.exists(summary_file_path):
                print(f"summary.txt found at {summary_file_path}.")
                with open(summary_file_path, 'r') as file:
                    transcription = file.read()
                    print("Successfully read transcription from summary.txt.")
            else:
                print("summary.txt is missing. Cannot proceed.")
                raise HTTPException(status_code=500, detail="No transcription provided and summary.txt is missing.")

        # Chunk the transcription into manageable parts
        chunks = chunk_text(transcription)
        print(f"Transcription split into {len(chunks)} chunks for summarization.")

        final_summary = []

        # Process each chunk
        for i, chunk in enumerate(chunks):
            print(f"Processing chunk {i+1}/{len(chunks)}")

            prompt = f"""
            Here is a transcription of a conversation. The conversation involves multiple people, and I want you to try your best to identify who is speaking based on the context, tone, and content. Summarize the key points and label the speakers where possible.

            Transcription: {chunk}
            """

            try:
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You are an assistant that can identify speakers based on textual cues."},
                        {"role": "user", "content": prompt}
                    ]
                )
                summary = response.choices[0].message.content
                final_summary.append(summary)
                print(f"Successfully received summary for chunk {i+1}")

            except Exception as e:
                print(f"GPT-4 API failed for chunk {i+1} with error: {e}")
                raise HTTPException(status_code=500, detail="Error while generating summary.")

        # Combine the chunked summaries into one
        combined_summary = " ".join(final_summary)

        # 🚨 feed a model summary to the agent to help it always get the structure right

        # Send the combined summary for final summarization
        print("Sending combined summary to GPT-4 for final summarization.")
        final_prompt = f"""
        Here is a combined summary of a transcription that was split into multiple chunks and summarized in chunks. 

        This meeting happened in the context of our company called Rainsound.ai. We build AI Agents for customers like Nvidia, Salesforce, and Microsoft.
        
        Some meetings are internal while others involve external entities like our finance lead or sales lead etc.
        There are stategy meetings, business operation meetings, customer-facing sales meetings, and delivery work sessions.

        When meetings begin with introductions, skip that part for the purpose of this summary except for external people. Represent everyone who spoke in this meeting in a concise list.

        Organize the the response into a one sentence intro and then 1-5 sections containing bullet points for key insights, and then an analysis at the end. 
        If any next actions were discussed please include those in the final analysis. 
        
        The title of each section should feel intuitive. 
        
        Throughout the entire response clearly mark who said what when relevant. 

        Propose potential next actions in a section at the very end called "Potential Next Actions".

        Combined Summary: {combined_summary}
        """

        try:
            final_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an assistant that provides concise summaries."},
                    {"role": "user", "content": final_prompt}
                ]
            )
            final_summary = final_response.choices[0].message.content
            print("Successfully received final summary.")

        except Exception as e:
            print(f"GPT-4 API failed for final summarization with error: {e}")
            raise HTTPException(status_code=500, detail="Error while generating final summary.")

        return {"transcription": transcription, "summary": final_summary}

    except Exception as e:
        print(f"An error occurred during the summarization process: {e}")
        raise HTTPException(status_code=500, detail=str(e))
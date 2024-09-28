<script>
	import * as Urls from '../lib/Urls.shared';
	let file;
	let transcription = '';
	let summary = '';
	let isLoadingTranscription = false;
	let isLoadingSummary = false;
	let error = '';

	// Handle file selection
	const handleFileChange = (event) => {
		file = event.target.files[0];
		error = ''; // Reset the error message when a new file is selected
		transcription = ''; // Reset transcription when new file is selected
		summary = ''; // Reset summary when new file is selected
	};

	// Transcribe the audio file
	const transcribeAudio = async () => {
		if (!file) {
			alert('Please select an audio file first.');
			return;
		}

		isLoadingTranscription = true;
		transcription = '';
		summary = '';
		error = '';

		const formData = new FormData();
		formData.append('file', file);

		try {
			const response = await fetch(`${Urls.apiRoot()}/transcribe`, {
				method: 'POST',
				body: formData
			});

			if (!response.ok) {
				const errorData = await response.json();
				throw new Error(errorData.detail || 'An error occurred during transcription.');
			}

			const data = await response.json();
			transcription = data.transcription;
		} catch (err) {
			error = err.message;
		} finally {
			isLoadingTranscription = false;
		}
	};

	// Summarize the transcription
	const summarizeTranscription = async () => {
		isLoadingSummary = true;
		error = '';

		try {
			const response = await fetch(`${Urls.apiRoot()}/summarize`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json'
				},
				body: JSON.stringify({ transcription })
			});

			if (!response.ok) {
				const errorData = await response.json();
				throw new Error(errorData.detail || 'An error occurred during summarization.');
			}

			const data = await response.json();
			summary = data.summary;
		} catch (err) {
			error = err.message;
		} finally {
			isLoadingSummary = false;
		}
	};
</script>

<div class="container">
	<h1>Audio Transcription with Whisper</h1>

	<!-- File input for selecting the audio file -->
	<input type="file" accept="audio/*" on:change={handleFileChange} />

	<!-- Transcribe button (displays while transcription is loading) -->
	<button
		on:click={transcribeAudio}
		disabled={isLoadingTranscription || !file}
		style="margin-top: 1rem;"
	>
		{#if isLoadingTranscription}
			Transcribing...
		{:else}
			Transcribe
		{/if}
	</button>

	<!-- Always show the "Summarize" button (can trigger summarization) -->
	<button on:click={summarizeTranscription} disabled={isLoadingSummary} style="margin-top: 1rem;">
		{#if isLoadingSummary}
			Summarizing...
		{:else}
			Summarize
		{/if}
	</button>

	<!-- Display transcription if available and no summary yet -->
	{#if transcription && !summary}
		<div class="transcription">
			<h2>Transcription:</h2>
			<p>{transcription}</p>
		</div>
	{/if}

	<!-- Display summary when it's ready -->
	{#if summary}
		<div class="summary">
			<h2>Summary:</h2>
			<p>{summary}</p>
		</div>
	{/if}

	<!-- Error message display -->
	{#if error}
		<div class="error">
			<p>Error: {error}</p>
		</div>
	{/if}
</div>

<style>
	.container {
		max-width: 600px;
		margin: 2rem auto;
		padding: 2rem;
		border: 1px solid #ddd;
		border-radius: 8px;
		text-align: center;
	}

	.transcription,
	.summary {
		margin-top: 1.5rem;
		padding: 1rem;
		border: 1px solid #eee;
		background-color: #f9f9f9;
		border-radius: 4px;
		white-space: pre-wrap;
	}

	.error {
		color: red;
		margin-top: 1rem;
	}
</style>

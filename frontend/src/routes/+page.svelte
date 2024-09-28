<script>
	import { onMount } from 'svelte';
	import * as Urls from '../lib/Urls.shared';
	let file;
	let transcription = '';
	let isLoading = false;
	let error = '';

	const handleFileChange = (event) => {
		file = event.target.files[0];
		error = ''; // Reset error message when a new file is selected
	};

	const transcribeAudio = async () => {
		if (!file) {
			alert('Please select an audio file first.');
			return;
		}

		isLoading = true;
		transcription = '';
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
			isLoading = false;
		}
	};
</script>

<div class="container">
	<h1>Audio Transcription with Whisper</h1>

	<input type="file" accept="audio/*" on:change={handleFileChange} />

	<button on:click={transcribeAudio} disabled={isLoading || !file} style="margin-top: 1rem;">
		{#if isLoading}
			Transcribing...
		{:else}
			Transcribe
		{/if}
	</button>

	{#if transcription}
		<div class="transcription">
			<h2>Transcription:</h2>
			<p>{transcription}</p>
		</div>
	{/if}

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

	.transcription {
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

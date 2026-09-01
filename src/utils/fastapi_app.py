# utils/fastapi_app.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio
import concurrent.futures

app = FastAPI()

# Will be set by main app to the MicrophoneSubscriber.buffer
audio_queue = None  # type: ignore
clients = set()


@app.on_event("startup")
async def startup_event():
    global forwarder_task
    loop = asyncio.get_event_loop()
    forwarder_task = loop.create_task(_queue_forwarder())


@app.on_event("shutdown")
async def shutdown_event():
    """Cancel the queue forwarder on shutdown."""
    global forwarder_task
    if forwarder_task:
        forwarder_task.cancel()
        await forwarder_task



async def _queue_forwarder():
    """Forward audio data from the multiprocessing queue to all WebSocket clients."""
    global audio_queue
    if audio_queue is None:
        return

    loop = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    while True:
        try:
            # Use a timeout to periodically check for cancellation
            data = await loop.run_in_executor(executor, lambda: audio_queue.get(timeout=0.5))
            if not data:
                continue

            to_remove = []
            for ws in list(clients):
                try:
                    await ws.send_bytes(data)
                except Exception:
                    to_remove.append(ws)
            for ws in to_remove:
                clients.discard(ws)

        except asyncio.CancelledError:
            break
        except Exception:
            # Ignore empty queue or other errors
            continue


@app.get("/", response_class=HTMLResponse)
async def index():
    """Minimal page to play audio from WebSocket."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>HoloLens Audio Stream</title>
    </head>
    <body>
        <h1>Audio Stream</h1>
        <button id="connect">Connect & Play</button>
        <button id="disconnect" disabled>Stop</button>
        <script>
        let ws = null;
        let audioContext = null;
        let gainNode = null;
        let isPlaying = false;
        let nextPlayTime = 0;
        const SAMPLE_RATE = 48000;
        const NUM_CHANNELS = 2;

        function playAudioData(audioData) {
            if (!audioContext || !isPlaying) return;
            try {
                const float32Array = new Float32Array(audioData.buffer);
                const samplesPerChannel = float32Array.length / NUM_CHANNELS;
                if (samplesPerChannel === 0) return;

                const audioBuffer = audioContext.createBuffer(
                    NUM_CHANNELS,
                    samplesPerChannel,
                    SAMPLE_RATE
                );

                if (NUM_CHANNELS === 1) {
                    audioBuffer.copyToChannel(float32Array, 0);
                } else {
                    const ch0 = float32Array.slice(0, samplesPerChannel);
                    const ch1 = float32Array.slice(samplesPerChannel);
                    audioBuffer.copyToChannel(ch0, 0);
                    audioBuffer.copyToChannel(ch1, 1);
                }

                const source = audioContext.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(gainNode);

                if (nextPlayTime < audioContext.currentTime) {
                    nextPlayTime = audioContext.currentTime;
                }

                source.start(nextPlayTime);
                nextPlayTime += audioBuffer.duration;

            } catch (e) {
                console.error('Audio play error:', e);
            }
        }

        document.getElementById('connect').onclick = async () => {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            gainNode = audioContext.createGain();
            gainNode.connect(audioContext.destination);
            await audioContext.resume();

            ws = new WebSocket('ws://' + window.location.host + '/audio');
            ws.binaryType = 'arraybuffer';

            ws.onopen = () => {
                isPlaying = true;
                document.getElementById('connect').disabled = true;
                document.getElementById('disconnect').disabled = false;
            };

            ws.onmessage = (event) => {
                const data = new Uint8Array(event.data);
                playAudioData(data);
            };

            ws.onclose = () => {
                isPlaying = false;
                document.getElementById('connect').disabled = false;
                document.getElementById('disconnect').disabled = true;
            };
        };

        document.getElementById('disconnect').onclick = () => {
            isPlaying = false;
            if (ws) ws.close();
            if (audioContext) {
                audioContext.close();
                audioContext = null;
            }
            nextPlayTime = 0;
        };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.websocket("/audio")
async def websocket_audio(ws: WebSocket):
    """Keep WebSocket clients registered to receive audio."""
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            await asyncio.sleep(10)  # just keep connection alive
    except WebSocketDisconnect:
        clients.discard(ws)

import os
import threading

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


class GroqProvider:
    """
    OpenAI-compatible chat provider.

    Defaults to Groq but honors env overrides, keeping the rest of
    JARVIS provider-independent (context 75):

        JARVIS_LLM_BASE_URL (default: Groq)
        JARVIS_LLM_API_KEY  (default: GROQ_API_KEY)
        JARVIS_LLM_MODEL    (default: openai/gpt-oss-20b)
    """

    def __init__(self):
        base_url = os.getenv(
            "JARVIS_LLM_BASE_URL",
            "https://api.groq.com/openai/v1",
        )

        api_key = os.getenv("JARVIS_LLM_API_KEY") or os.getenv(
            "GROQ_API_KEY"
        )

        if not api_key:
            raise ValueError(
                "No LLM API key set. Use GROQ_API_KEY (or JARVIS_LLM_API_KEY "
                "with JARVIS_LLM_BASE_URL for another provider)."
            )

        self.model = os.getenv("JARVIS_LLM_MODEL", "openai/gpt-oss-20b")

        # Timeout keeps the voice loop responsive: a hung API call can
        # never block listening for more than ~25 seconds.
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=25.0,
            max_retries=1,
        )

    def generate(self, prompt: str) -> str:
        """
        One generation pass. Optional interrupt support: Brain v3 and
        the orchestrator share a threading.Event here, so a spoken
        "stop" / "hey jarvis" DURING thinking aborts the in-flight
        call within ~0.2s instead of after the provider finishes.
        """

        abort = getattr(self, "abort_event", None)

        if abort is None:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self._messages(prompt),
            )

            return response.choices[0].message.content.strip()

        # Cancellable path: run the request in a worker thread and
        # watch the abort event in short bursts.
        result = {}

        def _worker():
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=self._messages(prompt),
                )

                result["text"] = (
                    response.choices[0].message.content.strip()
                )

            except Exception as error:
                result["error"] = error

        worker = threading.Thread(
            target=_worker,
            daemon=True,
        )

        worker.start()

        while worker.is_alive():
            worker.join(timeout=0.2)

            if abort.is_set():
                raise InterruptedError(
                    "thinking interrupted by the user"
                )

        if "error" in result:
            raise result["error"]

        return result.get("text", "")

    def _messages(self, prompt: str) -> list:
        return [
            {
                "role": "system",
                "content": (
                    "You are JARVIS, a personal desktop voice assistant. "
                    "Answer naturally and concisely. "
                    "For simple factual questions, answer in 1 or 2 sentences. "
                    "Do not use Markdown. "
                    "Do not use bullet points or numbered lists unless absolutely necessary. "
                    "Do not use emojis. "
                    "Do not use asterisks, hashtags, backticks, or decorative symbols. "
                    "Your response will be spoken aloud using text-to-speech, "
                    "so output clean natural spoken English."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]


if __name__ == "__main__":
    provider = GroqProvider()

    response = provider.generate(
        "What is the capital of India?"
    )

    print("JARVIS:", response)
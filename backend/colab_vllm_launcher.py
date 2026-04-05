"""
Launch a vLLM OpenAI-compatible server on Google Colab and expose it with ngrok.

Run this file inside a Colab notebook, or paste it into a single Colab cell.

Required Colab secrets:
- HF_TOKEN: Hugging Face token with access to meta-llama/Meta-Llama-3-8B-Instruct
- NGROK_AUTH_TOKEN: ngrok auth token

Optional environment variables:
- LLM_MODEL: defaults to meta-llama/Meta-Llama-3-8B-Instruct
- LLM_API_KEY: defaults to colab-vllm-key
- VLLM_PORT: defaults to 8000

Note:
- On a free Colab GPU, full Llama 3 8B can be tight on memory. If startup fails with OOM,
  reduce max model length further or move to a larger Colab GPU.
"""
import atexit
import getpass
import os
import subprocess
import sys
import time


MODEL_NAME = os.environ.get("LLM_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
API_KEY = os.environ.get("LLM_API_KEY", "colab-vllm-key")
PORT = int(os.environ.get("VLLM_PORT", "8000"))


def install_requirements():
    """Install only the packages needed for this Colab runtime."""
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "vllm", "pyngrok", "requests"]
    )


def read_colab_secret(name: str) -> str:
    """Read a secret from Colab secrets or environment variables."""
    value = os.environ.get(name)
    if value:
        return value

    try:
        from google.colab import userdata
        from google.colab import errors as colab_errors
    except ImportError:
        prompt = f"Enter {name}: "
        value = getpass.getpass(prompt).strip()
        if not value:
            raise RuntimeError(f"Missing required secret: {name}")
        os.environ[name] = value
        return value

    try:
        value = userdata.get(name)
        if value:
            return value
    except (colab_errors.SecretNotFoundError, colab_errors.NotebookAccessError, colab_errors.TimeoutException):
        pass

    prompt = (
        f"Enter {name} now, or stop and add it in Colab Secrets "
        f"(left sidebar > Secrets > add {name}): "
    )
    value = getpass.getpass(prompt).strip()
    if not value:
        raise RuntimeError(
            f"Missing required secret: {name}. "
            f"Set it in Colab Secrets or export it with os.environ['{name}'] before running."
        )

    os.environ[name] = value
    return value


def wait_for_server(api_key: str):
    """Wait until the vLLM server starts answering OpenAI-compatible requests."""
    import requests

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    last_error = None

    for _ in range(90):
        try:
            response = requests.get(
                f"http://127.0.0.1:{PORT}/v1/models",
                headers=headers,
                timeout=5,
            )
            if response.ok:
                return
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(5)

    raise RuntimeError(f"vLLM server did not become ready: {last_error}")


def main():
    install_requirements()

    from pyngrok import ngrok

    hf_token = read_colab_secret("HF_TOKEN")
    ngrok_token = read_colab_secret("NGROK_AUTH_TOKEN")

    os.environ["HF_TOKEN"] = hf_token
    os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

    ngrok.set_auth_token(ngrok_token)

    command = [
        "vllm",
        "serve",
        MODEL_NAME,
        "--host",
        "0.0.0.0",
        "--port",
        str(PORT),
        "--dtype",
        "half",
        "--gpu-memory-utilization",
        "0.90",
        "--max-model-len",
        "2048",
    ]
    if API_KEY:
        command.extend(["--api-key", API_KEY])

    print("Starting vLLM server...")
    process = subprocess.Popen(command)
    atexit.register(process.terminate)

    wait_for_server(API_KEY)

    tunnel = ngrok.connect(PORT, bind_tls=True)
    atexit.register(lambda: ngrok.disconnect(tunnel.public_url))

    print()
    print("vLLM is ready.")
    print(f"LLM_BASE_URL={tunnel.public_url}/v1")
    print(f"LLM_API_KEY={API_KEY}")
    print(f"LLM_MODEL={MODEL_NAME}")
    print()
    print("Keep this Colab runtime running while your backend uses the endpoint.")

    process.wait()


if __name__ == "__main__":
    main()

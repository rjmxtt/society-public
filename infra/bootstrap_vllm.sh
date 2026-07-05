#!/usr/bin/env bash
# Bootstrap a vLLM OpenAI-compatible server on a fresh GPU box (Runpod et al).
#
# Usage (on the GPU box):
#   ./bootstrap_vllm.sh huihui-ai/Qwen3-14B-abliterated
#   ./bootstrap_vllm.sh huihui-ai/Dolphin3.0-Llama3.1-8B-abliterated
#
# Serves the model on :8000 with guided-decoding (xgrammar) enabled, which is
# what src/vllm_client.py uses to hard-constrain committee votes to VOTE_SCHEMA.
#
# We run ONE model at a time (generator + committee share a model per D1), so a
# single 48GB card (L40S/A6000) serves either model in fp16. Swap models by
# re-running with a different id.
set -euo pipefail

MODEL="${1:?usage: bootstrap_vllm.sh <hf-model-id> [port]}"
PORT="${2:-8000}"

# The huihui-ai abliterated repos are GATED on HF. Before first run: accept the
# access terms on the model's HF page with your account, create a read token,
# and `export HF_TOKEN=hf_...` (transformers/vLLM pick it up automatically).
if [[ -z "${HF_TOKEN:-}" ]]; then
  echo "WARN: HF_TOKEN unset — gated repos (huihui-ai/*) will 401. See infra/README.md." >&2
fi

# vLLM picks a context length from the model config; cap KV-cache growth so the
# 14B fits comfortably on 48GB alongside the committee's parallel requests.
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_UTIL="${GPU_UTIL:-0.90}"

echo "== installing vLLM =="
pip install -q --upgrade pip
# hf_transfer is a standalone package in huggingface-hub 1.x (no longer an
# extra). It must be installed for HF_HUB_ENABLE_HF_TRANSFER=1 to work — with
# the env var set but the package missing, downloads error out.
pip install -q vllm hf_transfer
export HF_HUB_ENABLE_HF_TRANSFER=1   # faster weight download

echo "== serving ${MODEL} on :${PORT} (max_model_len=${MAX_MODEL_LEN}, gpu_util=${GPU_UTIL}) =="
# Recent vLLM auto-selects the structured-output backend (xgrammar) and removed
# the --guided-decoding-backend flag; guided_json in requests works without it.
exec vllm serve "${MODEL}" \
  --port "${PORT}" \
  --host 0.0.0.0 \
  --max-model-len "${MAX_MODEL_LEN}" \
  --gpu-memory-utilization "${GPU_UTIL}" \
  --disable-log-requests

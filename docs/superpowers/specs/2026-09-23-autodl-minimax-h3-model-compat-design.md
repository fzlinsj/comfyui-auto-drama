# AutoDL MiniMax H3 Model Compatibility Design

## Goal

Make the project's T2V, I2V, and R2V API workflows select H3 checkpoint filenames already exposed by the user's AutoDL ComfyUI image.

## Findings

- The AutoDL ComfyUI API is reachable on local port 6006 and reports an NVIDIA RTX 3090.
- Required H3 video nodes and video/audio VAEs are registered.
- The configured R2V CLIP and FL2VA/Ref2VA checkpoints are available.
- The I2V template refers to an unavailable uncensored CLIP filename.
- T2V, I2V, and R2V refer to unavailable Turbo LoRA filenames. The server exposes `minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors`.
- The server exposes `qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors`, which is an H3 Heretic CLIP alternative for I2V.

## Design

Update the T2V workflow and I2V/R2V API graph templates/builders to request the installed pruned ComfyUI Turbo LoRA filename. Update the I2V API template's CLIP selection to the installed H3 Heretic NVFP4 CLIP. Keep the R2V UNet and CLIP defaults unchanged because both are already present. Do not create model aliases or download files to the server.

## Testing and Documentation

Add focused tests that build each API graph and assert that their CLIP/LoRA selections match the AutoDL image's available filenames. Add a top-of-file changelog entry describing compatibility, verification, and operational impact as required by the repository instructions.

## Boundaries

- Do not submit a generation job as part of code verification; that consumes the user's rented GPU time.
- Do not change server files or download model weights.
- Existing local changes are preserved.

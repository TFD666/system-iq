# Docker

Build and run the hosted backend image from the repo root.

    docker build -t systemiq .
    docker run --rm -p 8000:8000 --env-file backend/.env -e HOSTED=1 -e ACCESS_CODES=label:code:5 systemiq

**Never bake a key, access code, or admin token into the image.** The Dockerfile copies no `.env` file and sets
no secret itself; all of that (`GROQ_API_KEY`, `OPENCODE_API_KEY`, `ACCESS_CODES`, `ADMIN_TOKEN`, ...) is passed in
at `docker run` time via `--env-file` / `-e`, never baked into a layer.

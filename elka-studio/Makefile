.PHONY: setup run-backend run-dev

setup:
bash scripts/install.sh

run-backend:
uvicorn backend.app.main:app --reload

run-dev:
bash scripts/run-dev.sh

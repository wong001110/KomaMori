.PHONY: api web test continuity up down

api:
	PYTHONPATH=apps/api/src uvicorn komamori.main:app --reload --port 8000

web:
	cd apps/web && npm run dev

test:
	PYTHONPATH=apps/api/src pytest

continuity:
	python scripts/continuity.py bootstrap

up:
	docker compose up --build

down:
	docker compose down

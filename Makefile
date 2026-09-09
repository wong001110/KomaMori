.PHONY: api web test continuity continuity-sync continuity-gate up down

api:
	PYTHONPATH=apps/api/src uvicorn komamori.main:app --reload --port 8000

web:
	cd apps/web && npm run dev

test:
	PYTHONPATH=apps/api/src pytest

continuity:
	python scripts/continuity.py bootstrap

continuity-sync:
	@test -n "$(MANIFEST)" || (echo "MANIFEST is required" && exit 2)
	python scripts/continuity.py manifest-sync "$(MANIFEST)" $(if $(COMMIT),--commit "$(COMMIT)",)

continuity-gate:
	@test -n "$(PHASE)" || (echo "PHASE is required" && exit 2)
	@test -n "$(COMMIT)" || (echo "COMMIT is required" && exit 2)
	python scripts/continuity.py gate "$(PHASE)" --commit "$(COMMIT)"

up:
	docker compose up --build

down:
	docker compose down

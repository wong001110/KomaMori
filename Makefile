.PHONY: api web test continuity continuity-sync continuity-capture continuity-gate continuity-review up down

api:
	PYTHONPATH=apps/api/src uvicorn komamori.main:app --reload --port 8000

web:
	cd apps/web && npm run dev

test:
	PYTHONPATH=apps/api/src pytest

continuity:
	python scripts/continuity_v03.py bootstrap

continuity-sync:
	@test -n "$(MANIFEST)" || (echo "MANIFEST is required" && exit 2)
	python scripts/continuity_v03.py manifest-sync "$(MANIFEST)" $(if $(COMMIT),--commit "$(COMMIT)",)

continuity-capture:
	@test -n "$(PHASE)" || (echo "PHASE is required" && exit 2)
	python scripts/continuity_v03.py capture-gate "$(PHASE)"

continuity-gate:
	@test -n "$(PHASE)" || (echo "PHASE is required" && exit 2)
	@test -n "$(COMMIT)" || (echo "COMMIT is required" && exit 2)
	python scripts/continuity_v03.py gate "$(PHASE)" --commit "$(COMMIT)"

continuity-review:
	@test -n "$(PHASE)" || (echo "PHASE is required" && exit 2)
	@test -n "$(COMMIT)" || (echo "COMMIT is required" && exit 2)
	python scripts/continuity_v03.py review-gate "$(PHASE)" --commit "$(COMMIT)"

up:
	docker compose up --build

down:
	docker compose down

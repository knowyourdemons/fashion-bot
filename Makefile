.PHONY: dev migrate seed test lint deploy

dev:
	docker-compose -f docker/docker-compose.yml up --build

migrate:
	docker-compose -f docker/docker-compose.yml exec app alembic upgrade head

seed:
	docker-compose -f docker/docker-compose.yml exec app python -m db.seeds.taxonomy_seed
	docker-compose -f docker/docker-compose.yml exec app python -m db.seeds.scoring_matrix_seed
	docker-compose -f docker/docker-compose.yml exec app python -m db.seeds.dev_seed

test:
	docker-compose -f docker/docker-compose.yml exec app python -m pytest tests/test_smoke.py tests/test_unit.py tests/test_integration.py -v --tb=short

test-smoke:
	docker-compose -f docker/docker-compose.yml exec app python -m pytest tests/test_smoke.py -v --tb=short

test-unit:
	docker-compose -f docker/docker-compose.yml exec app python -m pytest tests/test_unit.py -v --tb=short

test-integration:
	docker-compose -f docker/docker-compose.yml exec app python -m pytest tests/test_integration.py -v --tb=short

lint:
	ruff check .
	mypy .

deploy:
	docker-compose -f docker/docker-compose.yml build
	docker-compose -f docker/docker-compose.yml exec app python -m pytest tests/test_smoke.py tests/test_unit.py -v --tb=short
	docker-compose -f docker/docker-compose.yml up -d --remove-orphans
	docker-compose -f docker/docker-compose.yml exec app alembic upgrade head

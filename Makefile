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
	pytest tests/ -v --asyncio-mode=auto

lint:
	ruff check .
	mypy .

deploy:
	docker-compose -f docker/docker-compose.yml build
	docker-compose -f docker/docker-compose.yml run --rm app pytest tests/ -v --asyncio-mode=auto --tb=short
	docker-compose -f docker/docker-compose.yml up -d --remove-orphans
	docker-compose -f docker/docker-compose.yml exec app alembic upgrade head

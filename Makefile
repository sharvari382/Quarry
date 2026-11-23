.PHONY: help secrets up down logs scale dev-api dev-web test test-backend test-frontend lint load-test eval sample-data

help:
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

secrets: ## Print freshly generated secrets for .env
	@python3 -c "import secrets,base64,os;print('POSTGRES_PASSWORD='+secrets.token_urlsafe(24));print('REDIS_PASSWORD='+secrets.token_urlsafe(24));print('JWT_SECRET='+secrets.token_urlsafe(64));print('DATA_ENCRYPTION_KEYS='+base64.urlsafe_b64encode(os.urandom(32)).decode())"

up: ## Build and start the full stack on http://localhost:8080
	docker compose up -d --build

down: ## Stop the stack (data volumes are kept)
	docker compose down

logs: ## Follow API and proxy logs
	docker compose logs -f api web

scale: ## Run N API replicas, e.g. make scale N=6
	docker compose up -d --scale api=$(N)

dev-api: ## Run the API locally with SQLite and hot reload
	cd backend && uvicorn app.main:app --reload --port 8000

dev-web: ## Run the frontend dev server (proxies /api to :8000)
	cd frontend && npm run dev

test: test-backend test-frontend ## Run every automated test suite

test-backend: ## Unit, integration and security tests with coverage
	cd backend && python -m pytest --cov=app --cov-report=term-missing

test-frontend: ## Type-check and component tests
	cd frontend && npm run typecheck && npm test

lint: ## Static checks
	cd backend && ruff check app tests

load-test: ## Load test a running stack: make load-test USERS=200 HOST=http://localhost:8080
	cd backend && locust -f tests/load/locustfile.py --headless -u $(or $(USERS),100) -r 10 -t 2m --host $(or $(HOST),http://localhost:8080)

eval: ## Score answer accuracy against a real LLM (needs an API key in env)
	cd backend && python -m tests.evals.run_evals

sample-data: ## Regenerate sample_data/*.csv
	python3 scripts/generate_sample_data.py

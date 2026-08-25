.PHONY: up down logs build config

up:
	docker compose up -d --build
down:
	docker compose down
logs:
	docker compose logs -f
build:
	docker compose build
config:
	docker compose config -q

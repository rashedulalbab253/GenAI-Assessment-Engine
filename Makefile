docker-up:
	docker compose down && docker compose up --build -d

docker-logs:
	docker logs -f ai_exam_system

git-push:
	git add . && git commit -m "Modified Backend" && git push -u origin main
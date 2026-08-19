# DockIQ — Phase 0 convenience targets.
# On Windows without `make`, run the underlying `docker compose` commands directly.

.PHONY: up down logs ps agent agent-down restart clean enroll hosts

up:            ## Start the control-plane stack
	docker compose up -d --build

down:          ## Stop the stack (keep volumes)
	docker compose down

logs:          ## Tail backend logs
	docker compose logs -f backend

ps:            ## Show stack status
	docker compose ps

agent:         ## Run a local test agent (shares the compose network)
	docker compose --profile agent up -d --build agent

agent-down:    ## Stop the local test agent
	docker compose stop agent

restart:       ## Restart the backend only
	docker compose restart backend

clean:         ## Stop the stack and delete volumes (DESTROYS DATA)
	docker compose down -v

enroll:        ## Enroll a host and print the response
	curl -s -X POST http://localhost:8080/api/v1/agents/enroll \
		-H 'Content-Type: application/json' \
		-d '{"host_name":"manual-host"}'

hosts:         ## List enrolled hosts
	curl -s http://localhost:8080/api/v1/hosts

.PHONY: server web clean start stop restart status

server:
	cd server && go run ./cmd/server/

web:
	cd web && npm run dev

start:
	@mkdir -p /tmp/bug_agent_logs
	@cd server && nohup go run ./cmd/server/ >/tmp/bug_agent_logs/server.log 2>&1 &
	@cd web && nohup npm run dev -- --host 0.0.0.0 --port 5678 --strictPort >/tmp/bug_agent_logs/web.log 2>&1 &
	@i=0; \
	while [ $$i -lt 40 ]; do \
		if curl -sS http://127.0.0.1:8765/healthz >/dev/null 2>&1; then \
			break; \
		fi; \
		i=$$((i+1)); \
		sleep 1; \
	done
	@echo "started: backend(8765) + frontend(5678)"
	@$(MAKE) status

stop:
	@PIDS_8765=$$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true); \
	if [ -n "$$PIDS_8765" ]; then kill -9 $$PIDS_8765; fi
	@PIDS_5678=$$(lsof -tiTCP:5678 -sTCP:LISTEN 2>/dev/null || true); \
	if [ -n "$$PIDS_5678" ]; then kill -9 $$PIDS_5678; fi
	@echo "stopped: backend(8765) + frontend(5678)"

restart:
	@$(MAKE) stop
	@$(MAKE) start

status:
	@echo "--- listen ---"
	@lsof -nP -iTCP:8765 -sTCP:LISTEN 2>/dev/null || echo "backend(8765): not listening"
	@lsof -nP -iTCP:5678 -sTCP:LISTEN 2>/dev/null || echo "frontend(5678): not listening"
	@echo "--- health ---"
	@curl -sS http://127.0.0.1:8765/healthz 2>/dev/null || echo "backend healthz unavailable"
	@echo

clean:
	rm -f server/bug_agent.db

.PHONY: all setup run-dev run-frontend stop clean

# Default target
all: run-dev

# Sets up the entire project
setup:
@echo "Setting up eLKA Studio..."
@bash scripts/install.sh

# Runs the full development stack (backend, celery, redis)
run-dev:
@echo "Starting development servers... (Use Ctrl+C to stop)"
@cd backend && bash ../scripts/run-dev.sh

# (Optional but helpful) Runs the frontend development server
run-frontend:
@echo "Starting frontend development server... (Use Ctrl+C to stop)"
@cd frontend && npm run dev

# Stops background services started by run-dev (e.g., Docker)
stop:
@echo "Stopping background services..."
@cd backend && bash ../scripts/run-dev.sh stop-services

# Removes generated files
clean:
@echo "Cleaning up project..."
@rm -rf backend/venv frontend/node_modules
@find . -name "__pycache__" -type d -exec rm -r {} + 2>/dev/null
